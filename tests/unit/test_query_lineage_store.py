"""get_query_lineage: production service_count counts real service ids and matched traces carry
`service`; the Test Set origin is scoped to the dataset the evaluations ran against; the
forge queries endpoint reports provenance from the fields the store actually returns."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

RUN = "run1"


def _production_trace(index: int, service_id: str) -> RetrievalTrace:
    source = OperatorSpan("source", "SOURCE", "source", (), "FIRED", 2.0, outputs=(Candidate(doc_id="d1", score=1.0, rank=1),))
    return RetrievalTrace(
        trace_id=f"prod-{index}", service_id=service_id, run_id=None, query_id=f"live-{index}", query_text="live",
        pipeline_id="p", spans=(source,), final_op_ids=("source",),
        timing=TraceTiming(wall_clock_ms=2.0, critical_path_ms=2.0, operator_sum_ms=2.0),
        metadata={"predicted_difficulty": "easy", "suspected_failures": ["source_miss"]},
    )


def _forge_query(text: str, difficulty: str) -> dict:
    return {
        "query_id": "q1", "text": text, "scenario_id": "s1", "query_type": "temporal",
        "difficulty_label": difficulty, "failure_category": "source_miss", "validated": True,
        "positive_doc_ids": ["d1"],
    }


async def _seed(db_path: Path) -> SQLiteStore:
    store = SQLiteStore(str(db_path))
    await store.init_db()
    summary = {"schema_version": 1, "corpus_size": 37, "total_scenarios": 1, "total_queries": 1, "validated": 1, "validation_coverage": 1.0}
    await store.save_forge_dataset("ds-old", json.dumps({**summary, "dataset_id": "ds-old"}), "/corpora/old.jsonl", "/out/old")
    await store.save_forge_queries("ds-old", json.dumps([_forge_query("old wording", "hard")]))
    await store.save_forge_dataset("ds-new", json.dumps({**summary, "dataset_id": "ds-new"}), "/corpora/new.jsonl", "/out/new")
    await store.save_forge_queries("ds-new", json.dumps([_forge_query("new wording", "easy")]))
    await store.save_run(RUN, "exp", json.dumps({"dataset": {"name": "forge"}}))
    await store.save_run_manifest(RUN, {"schema_version": 3, "forge_dataset_id": "ds-new"})
    await store.save_run_queries(RUN, [SimpleNamespace(query_id="q1", text="new wording")], "forge")
    await store.save_metric(RUN, "bm25", "q1", 0, "recall", 10, 1.0)
    await store.finish_run(RUN)
    await store.save_traces([_production_trace(0, "svc-a"), _production_trace(1, "svc-b"), _production_trace(2, "svc-a")])
    return store


@pytest.mark.asyncio
async def test_forge_origin_is_scoped_to_the_evaluated_dataset(tmp_path: Path) -> None:
    store = await _seed(tmp_path / "lineage.db")
    lineage = await store.get_query_lineage("q1")
    assert lineage["origin"]["source"] == "forge"
    assert lineage["origin"]["forge"]["dataset_id"] == "ds-new"
    assert lineage["origin"]["query_text"] == "new wording"
    assert lineage["evaluations"][0]["run_id"] == RUN


@pytest.mark.asyncio
async def test_production_matches_count_distinct_services(tmp_path: Path) -> None:
    store = await _seed(tmp_path / "services.db")
    lineage = await store.get_query_lineage("q1")
    matches = lineage["production_matches"]
    assert matches["match_difficulty"] == "easy"
    assert matches["summary"]["trace_count"] == 3
    assert matches["summary"]["service_count"] == 2
    assert {trace["service"] for trace in matches["traces"]} == {"svc-a", "svc-b"}
    assert all(trace["service"] == trace["service_id"] for trace in matches["traces"])
    assert all("total_latency_ms" in trace for trace in matches["traces"])


@pytest.mark.asyncio
async def test_lineage_endpoint_traces_carry_service(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    await _seed(db_path)
    registry = DbRegistry([str(db_path)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    body = client.get(f"/dbs/{registry.default_db_id}/query/q1/lineage").json()
    assert body["production_matches"]["summary"]["service_count"] == 2
    assert all("service" in trace for trace in body["production_matches"]["traces"])


@pytest.mark.asyncio
async def test_forge_queries_provenance_is_populated(tmp_path: Path) -> None:
    db_path = tmp_path / "forge.db"
    await _seed(db_path)
    registry = DbRegistry([str(db_path)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    body = client.get(f"/dbs/{registry.default_db_id}/forge/datasets/ds-new/queries?limit=10").json()
    assert body["total"] == 1 and body["items"][0]["query_id"] == "q1"
    provenance = body["provenance"]
    assert provenance["dataset_id"] == "ds-new"
    assert provenance["corpus_path"] == "/corpora/new.jsonl"
    assert provenance["output_dir"] == "/out/new"
    assert provenance["total_queries"] == 1 and provenance["corpus_size"] == 37
    assert provenance["validation_coverage"] == 1.0
    assert provenance["created_at"]

    hidden = TestClient(create_app(registry=DbRegistry([str(db_path)], read_only=True), enable_uploads=False))
    ro = hidden.get(f"/dbs/{registry.default_db_id}/forge/datasets/ds-new/queries?limit=10").json()
    assert ro["provenance"]["corpus_path"] == "new.jsonl" and ro["provenance"]["output_dir"] == "new"
