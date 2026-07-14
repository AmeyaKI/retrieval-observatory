from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
from retrieval_observatory.types import Query


async def _seed(path: Path, marker: str) -> None:
    store = SQLiteStore(str(path))
    await store.init_db()
    await store.save_run("run", marker, json.dumps({"dataset": {"name": marker}}))
    await store.save_run_queries("run", [Query(query_id="shared", text=f"query-{marker}")], marker)
    await store.save_qrels("run", {"shared": {f"gold-{marker}": 1}})
    await store.save_query_diagnostics([{
        "run_id": "run",
        "query_id": "shared",
        "pipeline_id": "pipeline",
        "difficulty_bucket": "hard",
        "failure_labels": ["candidate_miss"],
        "missing_relevant_ids": [f"gold-{marker}"],
        "stage_hits": {"0": []},
        "diagnostic_evidence": [{
            "label": "candidate_miss",
            "evidence_class": "measured",
            "method": "observed_stage_transition_v1",
            "reason": marker,
            "doc_ids": [],
            "threshold": None,
        }],
    }])
    candidates = [
        Candidate(doc_id=f"{marker}-{index}", score=1.0, rank=index + 1, origin_op_ids=["source"])
        for index in range(3)
    ]
    await store.save_trace_v2(RetrievalTraceV2(
        trace_id=f"trace-{marker}",
        run_id="run",
        query_id="shared",
        query_text=f"query-{marker}",
        pipeline_id="pipeline",
        spans=[OperatorSpan(
            op_id="source",
            op_type="SOURCE",
            op_name="source",
            parent_ids=[],
            status="FIRED",
            deterministic=True,
            replay_policy="EXACT",
            latency_ms=1.0,
            outputs=candidates,
        )],
        total_latency_ms=1.0,
        final_op_id="source",
    ))


@pytest.mark.asyncio
async def test_query_evidence_is_database_scoped_and_bounded(tmp_path: Path) -> None:
    path_a = tmp_path / "alpha.db"
    path_b = tmp_path / "beta.db"
    await _seed(path_a, "alpha")
    await _seed(path_b, "beta")
    registry = DbRegistry([str(path_a), str(path_b)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    alpha = client.get("/dbs/alpha/runs/run/queries/shared/evidence?candidate_limit=2")
    beta = client.get("/dbs/beta/runs/run/queries/shared/evidence?candidate_limit=2")

    assert alpha.status_code == beta.status_code == 200
    assert alpha.json()["scope"] == {"db_id": "alpha", "run_id": "run", "query_id": "shared"}
    assert alpha.json()["ground_truth"]["relevant_doc_ids"] == ["gold-alpha"]
    assert beta.json()["ground_truth"]["relevant_doc_ids"] == ["gold-beta"]
    alpha_span = alpha.json()["traces"][0]["spans"][0]
    assert [candidate["doc_id"] for candidate in alpha_span["outputs"]] == ["alpha-0", "alpha-1"]
    assert alpha_span["outputs_total"] == 3
    assert alpha_span["outputs_truncated"] is True
    assert alpha.json()["diagnostics"][0]["diagnostic_evidence"][0]["reason"] == "alpha"

    report = client.get("/dbs/alpha/runs/run/report")
    assert report.status_code == 200
    assert report.json()["run_id"] == "run"
    assert report.json()["dominant_issue"] == {"label": "candidate_miss", "query_count": 1}
    overview = client.get("/dbs/alpha/runs/run/overview")
    assert overview.json()["report"]["next_action"]


@pytest.mark.asyncio
async def test_legacy_global_evidence_route_rejects_ambiguous_database_scope(tmp_path: Path) -> None:
    path_a = tmp_path / "alpha.db"
    path_b = tmp_path / "beta.db"
    await _seed(path_a, "alpha")
    await _seed(path_b, "beta")
    registry = DbRegistry([str(path_a), str(path_b)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    response = client.get("/query/shared/lineage")

    assert response.status_code == 400
    assert "Explicit db_id" in response.json()["detail"]
