from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import (
    CaptureMetadata,
    Candidate,
    OperatorSpan,
    RetrievalTrace,
)


def _trace(*, partial: bool = False, redacted: bool = False) -> RetrievalTrace:
    kept = Candidate(
        "doc-kept",
        1.0,
        1,
        output_rank=1,
        candidate_id="kept",
        logical_chunk_id="chunk:kept",
        metadata={"preview": "private retained content"},
    )
    lost = Candidate(
        "doc-lost",
        0.8,
        2,
        output_rank=2,
        candidate_id="lost",
        logical_chunk_id="chunk:lost",
    )
    lost_input = Candidate(
        "doc-lost",
        0.8,
        2,
        output_rank=None,
        candidate_id="lost",
        logical_chunk_id="chunk:lost",
        decision_reason=None if partial else "threshold",
        decision_evidence="unavailable" if partial else "recorded",
    )
    final = Candidate(
        "doc-kept",
        1.1,
        1,
        output_rank=1,
        candidate_id="kept-final",
        logical_chunk_id="chunk:kept",
        parent_candidate_ids=("kept",),
        decision_reason="transformed",
        decision_evidence="recorded",
        metadata={"preview": "private retained content"},
    )
    return RetrievalTrace(
        trace_id="trace-1",
        service_id="search",
        run_id="run-a",
        query_id="q-1",
        query_text="private query",
        pipeline_id="pipeline-a",
        spans=(
            OperatorSpan.source("retrieve", "retrieve", (kept, lost)),
            OperatorSpan(
                "filter",
                "FILTER",
                "filter",
                ("retrieve",),
                "FIRED",
                1.0,
                input_groups={"retrieve": (kept, lost_input)},
                outputs=(final,),
                params={"branch_id": "quality"},
            ),
        ),
        final_op_ids=("filter",),
        capture=CaptureMetadata(
            candidates_truncated=partial,
            redacted_field_count=1 if redacted else 0,
            lineage_evidence="partial" if partial else "recorded",
        ),
    )


async def _seed(
    db_path: Path,
    *,
    partial: bool = False,
    redacted: bool = False,
    with_qrels: bool = True,
) -> DbRegistry:
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run("run-a", "lineage", "{}")
    await store.save_trace(_trace(partial=partial, redacted=redacted))
    if with_qrels:
        await store.save_qrels("run-a", {"q-1": {"chunk:kept": 0, "chunk:lost": 1}})
    await store.save_run_manifest(
        "run-a",
        {
            "evidence_profile": {
                "lineage": {"qrel_to_chunk_mapping_coverage": 1.0}
            }
        },
    )
    return DbRegistry([str(db_path)])


@pytest.mark.asyncio
async def test_query_lineage_api_returns_graph_accounting_and_readiness(tmp_path) -> None:
    registry = await _seed(tmp_path / "lineage.db")
    db_id = registry.list_db_ids()[0]
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    response = client.get(f"/dbs/{db_id}/runs/run-a/queries/q-1/candidate-lineage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"]["scope"] == "lineage_diagnosis"
    assert payload["readiness"]["status"] == "READY"
    assert payload["accounting"]["relevant_dropped_at_stage"] == 1
    assert payload["graph"]["edges"]
    assert payload["graph"]["nodes"][0]["node_id"].startswith("trace-1:")
    assert payload["traces"][0]["pipeline_id"] == "pipeline-a"


@pytest.mark.asyncio
async def test_passport_api_does_not_return_raw_preview_when_redacted(tmp_path) -> None:
    registry = await _seed(tmp_path / "redacted.db", redacted=True)
    db_id = registry.list_db_ids()[0]
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    payload = client.get(
        f"/dbs/{db_id}/runs/run-a/queries/q-1/candidates/kept-final"
    ).json()

    assert payload["candidate_id"] == "kept-final"
    assert payload["source"]["preview"] is None
    assert payload["outcome"]["kind"] == "irrelevant_retained"
    assert payload["relevant"] is False
    assert payload["pipelines"]


@pytest.mark.asyncio
async def test_partial_lineage_returns_200_with_blocked_readiness(tmp_path) -> None:
    registry = await _seed(tmp_path / "partial.db", partial=True)
    db_id = registry.list_db_ids()[0]
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    response = client.get(f"/dbs/{db_id}/runs/run-a/queries/q-1/candidate-lineage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"]["status"] == "BLOCK"
    assert "lineage_incomplete" in {
        node["outcome"]["kind"] for node in payload["graph"]["nodes"]
    }


@pytest.mark.asyncio
async def test_lineage_accounting_endpoint_and_missing_query_boundary(tmp_path) -> None:
    registry = await _seed(tmp_path / "accounting.db")
    db_id = registry.list_db_ids()[0]
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    accounting = client.get(
        f"/dbs/{db_id}/runs/run-a/queries/q-1/lineage-accounting"
    )
    missing = client.get(
        f"/dbs/{db_id}/runs/run-a/queries/missing/candidate-lineage"
    )

    assert accounting.status_code == 200
    assert accounting.json()["accounting"]["relevant_dropped_at_stage"] == 1
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_unlabeled_and_unobserved_candidates_do_not_become_false(tmp_path) -> None:
    registry = await _seed(tmp_path / "unlabeled.db", with_qrels=False)
    db_id = registry.list_db_ids()[0]
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    observed = client.get(
        f"/dbs/{db_id}/runs/run-a/queries/q-1/candidates/kept-final"
    )
    unobserved = client.get(
        f"/dbs/{db_id}/runs/run-a/queries/q-1/candidates/not-captured"
    )

    assert observed.status_code == 200
    assert observed.json()["relevance"]["kind"] == "unknown"
    assert observed.json()["outcome"]["kind"] == "unknown_relevance"
    assert observed.json()["relevant"] is None
    assert unobserved.status_code == 200
    assert unobserved.json()["readiness"]["status"] == "BLOCK"
    assert unobserved.json()["outcome"]["kind"] == "lineage_incomplete"
