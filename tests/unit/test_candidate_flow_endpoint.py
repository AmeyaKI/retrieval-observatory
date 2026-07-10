from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2

RUN_ID = "run1"


def _trace() -> RetrievalTraceV2:
    """SOURCE(d1,d2) -> FILTER drops d2."""
    source = OperatorSpan(
        op_id="source_bm25", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["source_bm25"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["source_bm25"]),
        ],
    )
    filt = OperatorSpan(
        op_id="filter_cap", op_type="FILTER", op_name="cap", parent_ids=["source_bm25"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        inputs=source.outputs, outputs=[source.outputs[0]],
    )
    return RetrievalTraceV2(
        trace_id="t_q0", run_id=RUN_ID, query_id="q0", query_text="q",
        pipeline_id="p", spans=[source, filt], total_latency_ms=2.0, final_op_id="filter_cap",
    )


@pytest.fixture
async def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "flow.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(RUN_ID, "flow-test", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_trace_v2(_trace())
    return db_path


@pytest.mark.asyncio
async def test_dropped_candidate_flow(seeded_db: Path) -> None:
    registry = DbRegistry([str(seeded_db)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/queries/q0/candidates/d2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == "d2"
    pipeline = body["pipelines"][0]
    hist = pipeline["history"]
    assert hist["introduced_at"] == "source_bm25"
    assert hist["dropped_at"] == "filter_cap"
    assert hist["dropped_reason"] == "filtered"
    assert hist["survived"] is False
    # Replay assumptions for the dropping operator are exposed for inspection.
    assert pipeline["drop_replay_assumptions"] is not None
    assert pipeline["drop_replay_assumptions"]["strategy"] == "filter_passthrough_inputs"


@pytest.mark.asyncio
async def test_survivor_candidate_flow(seeded_db: Path) -> None:
    registry = DbRegistry([str(seeded_db)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/queries/q0/candidates/d1")
    assert resp.status_code == 200
    hist = resp.json()["pipelines"][0]["history"]
    assert hist["survived"] is True
    assert hist["final_rank"] == 1
    assert hist["dropped_at"] is None


@pytest.mark.asyncio
async def test_missing_query_returns_404(seeded_db: Path) -> None:
    registry = DbRegistry([str(seeded_db)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db_id = registry.list_db_ids()[0]
    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/queries/nope/candidates/d1")
    assert resp.status_code == 404
