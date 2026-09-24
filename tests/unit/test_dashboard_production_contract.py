"""Production trace API contract: the flattened list/detail/service shapes the retained trace
routes return, checked on real responses so historical traces stay readable."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import (
    PRODUCTION_SERVICE_KEYS,
    PRODUCTION_TRACE_DETAIL_KEYS,
    PRODUCTION_TRACE_ROW_KEYS,
    PRODUCTION_TRACE_STAGE_KEYS,
    create_app,
)
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

# Optional: `retobs demo` output (gitignored). RETOBS_DEMO_DB overrides the default location.
DEMO_DB = Path(os.environ.get("RETOBS_DEMO_DB", Path(__file__).resolve().parents[2] / ".retobs" / "demo" / "results.db"))


def _production_trace(index: int, difficulty: str | None, suspected: list[str]) -> RetrievalTrace:
    source = OperatorSpan(
        "source", "SOURCE", "source", (), "FIRED", 4.0,
        outputs=(Candidate(doc_id="d1", score=1.0, rank=1), Candidate(doc_id="d2", score=0.5, rank=2)),
    )
    rerank = OperatorSpan(
        "rerank", "RERANK", "rerank", ("source",), "FIRED", 6.0,
        inputs=source.outputs, outputs=(Candidate(doc_id="d2", score=0.9, rank=1),),
    )
    metadata = {"suspected_failures": suspected}
    if difficulty is not None:
        metadata["predicted_difficulty"] = difficulty
    return RetrievalTrace(
        trace_id=f"t{index}", service_id="svc", run_id=None, query_id=f"q{index}", query_text=f"query {index}",
        pipeline_id="p", spans=(source, rerank), final_op_ids=("rerank",),
        timing=TraceTiming(wall_clock_ms=10.0, critical_path_ms=10.0, operator_sum_ms=10.0),
        metadata=metadata,
    )


@pytest.fixture
async def production_client(tmp_path: Path) -> TestClient:
    path = tmp_path / "prod.db"
    store = SQLiteStore(str(path))
    await store.init_db()
    await store.save_traces([
        _production_trace(0, "hard", ["source_miss"]),
        _production_trace(1, "hard", []),
        _production_trace(2, "easy", ["reranker_drop"]),
        _production_trace(3, None, []),
    ])
    return TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))


def _assert_trace_row_contract(item: dict) -> None:
    missing = PRODUCTION_TRACE_ROW_KEYS - set(item)
    assert not missing, f"production trace row is missing UI fields: {sorted(missing)}"
    assert item["service"] == item["service_id"]
    assert isinstance(item["total_latency_ms"], (int, float))
    assert isinstance(item["suspected_failures"], list)
    # Raw trace payload stays available for the monitor analytics.
    assert "spans" in item and "timing" in item


def _assert_trace_detail_contract(item: dict) -> None:
    missing = PRODUCTION_TRACE_DETAIL_KEYS - set(item)
    assert not missing, f"production trace detail is missing UI fields: {sorted(missing)}"
    assert item["stages"], "detail must expose flattened per-stage candidate lists"
    for stage in item["stages"]:
        stage_missing = PRODUCTION_TRACE_STAGE_KEYS - set(stage)
        assert not stage_missing, f"stage is missing UI fields: {sorted(stage_missing)}"
        for document in stage["documents"]:
            assert {"id", "score", "rank"} <= set(document)


def test_services_expose_service_id_and_alias(production_client: TestClient) -> None:
    db = production_client.get("/dbs").json()[0]["db_id"]
    services = production_client.get(f"/dbs/{db}/production/services").json()
    assert len(services) == 1
    assert PRODUCTION_SERVICE_KEYS <= set(services[0])
    assert services[0]["service_id"] == services[0]["service"] == "svc"
    assert services[0]["trace_count"] == 4


def test_trace_list_and_detail_are_flattened(production_client: TestClient) -> None:
    db = production_client.get("/dbs").json()[0]["db_id"]
    page = production_client.get(f"/dbs/{db}/production/traces?service_id=svc").json()
    assert page["total"] == 4 and len(page["items"]) == 4
    for item in page["items"]:
        _assert_trace_row_contract(item)
    by_id = {item["trace_id"]: item for item in page["items"]}
    assert by_id["t0"]["predicted_difficulty"] == "hard"
    assert by_id["t0"]["suspected_failures"] == ["source_miss"]
    assert by_id["t3"]["predicted_difficulty"] is None
    assert by_id["t0"]["total_latency_ms"] == 10.0

    detail = production_client.get(f"/dbs/{db}/production/traces/t0").json()
    _assert_trace_detail_contract(detail)
    assert [stage["stage_id"] for stage in detail["stages"]] == ["source", "rerank"]
    assert detail["stages"][0]["candidate_count"] == 2


def test_trace_list_filters_difficulty_and_suspected(production_client: TestClient) -> None:
    db = production_client.get("/dbs").json()[0]["db_id"]
    base = f"/dbs/{db}/production/traces?service_id=svc"
    hard = production_client.get(f"{base}&difficulty=hard").json()
    assert hard["total"] == 2 and {item["trace_id"] for item in hard["items"]} == {"t0", "t1"}
    suspected = production_client.get(f"{base}&suspected_only=true").json()
    assert suspected["total"] == 2 and {item["trace_id"] for item in suspected["items"]} == {"t0", "t2"}
    both = production_client.get(f"{base}&difficulty=hard&suspected_only=true").json()
    assert both["total"] == 1 and both["items"][0]["trace_id"] == "t0"
    none = production_client.get(f"{base}&difficulty=nonexistent").json()
    assert none["total"] == 0 and none["items"] == []
    # Pagination applies after filtering, and total reflects the filtered count.
    paged = production_client.get(f"{base}&suspected_only=true&limit=1").json()
    assert paged["total"] == 2 and len(paged["items"]) == 1 and paged["next_offset"] == 1


@pytest.mark.skipif(not DEMO_DB.is_file(), reason="`retobs demo` output not present")
def test_demo_database_production_contract() -> None:
    registry = DbRegistry([str(DEMO_DB)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db = registry.default_db_id
    services = client.get(f"/dbs/{db}/production/services").json()
    assert services and all(PRODUCTION_SERVICE_KEYS <= set(service) for service in services)
    service = services[0]["service_id"]
    assert services[0]["service"] == service

    page = client.get(f"/dbs/{db}/production/traces?service_id={service}&limit=500").json()
    assert page["items"]
    for item in page["items"]:
        _assert_trace_row_contract(item)
    hard_count = sum(1 for item in page["items"] if item["metadata"].get("predicted_difficulty") == "hard")
    suspected_count = sum(1 for item in page["items"] if item["metadata"].get("suspected_failures"))
    assert client.get(f"/dbs/{db}/production/traces?service_id={service}&difficulty=hard").json()["total"] == hard_count
    assert client.get(f"/dbs/{db}/production/traces?service_id={service}&suspected_only=true").json()["total"] == suspected_count

    detail = client.get(f"/dbs/{db}/production/traces/{page['items'][0]['trace_id']}").json()
    _assert_trace_detail_contract(detail)
