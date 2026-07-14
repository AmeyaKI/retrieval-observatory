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


def _trace(query_id: str, *, filter_drops: bool) -> RetrievalTraceV2:
    """SOURCE -> FILTER, where FILTER sometimes drops the gold doc "d2"."""
    source = OperatorSpan(
        op_id="source_bm25", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["source_bm25"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["source_bm25"]),
        ],
    )
    kept = [source.outputs[0]] if filter_drops else list(source.outputs)
    filt = OperatorSpan(
        op_id="filter_cap", op_type="FILTER", op_name="cap", parent_ids=[source.op_id],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        inputs=source.outputs, outputs=kept,
    )
    return RetrievalTraceV2(
        trace_id=f"t_{query_id}", run_id=RUN_ID, query_id=query_id, query_text="q",
        pipeline_id="p", spans=[source, filt], total_latency_ms=2.0, final_op_id=filt.op_id,
    )


@pytest.fixture
async def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "attr.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(RUN_ID, "attribution-test", json.dumps({"dataset": {"name": "custom"}}))
    # d2 is the gold doc; FILTER drops it for half the queries -- a real, measurable effect.
    await store.save_qrels(RUN_ID, {f"q{i}": {"d2": 1} for i in range(20)})
    for i in range(20):
        await store.save_trace_v2(_trace(f"q{i}", filter_drops=(i % 2 == 0)))
    return db_path


@pytest.mark.asyncio
async def test_operator_attribution_uses_persisted_qrels(seeded_db: Path) -> None:
    registry = DbRegistry([str(seeded_db)])
    app = create_app(registry=registry, enable_uploads=False)
    client = TestClient(app)
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/operator-attribution?metric=recall&k=10")
    assert resp.status_code == 200
    rows = resp.json()

    filter_rows = [r for r in rows if r["op_id"] == "filter_cap"]
    assert filter_rows, "expected a result row for filter_cap"
    row = filter_rows[0]

    # Real ground truth was found (via run_qrels), not the old always-empty qrel_ids path.
    assert row["result_status"] == "replayed"
    assert row["evidence_class"] == "replayed"
    assert row["n_pairs"] == 20
    # FILTER drops the gold doc in exactly half the traces: with-FILTER recall averages 0.5,
    # without-FILTER (counterfactual restores the dropped doc) recall is 1.0 -> delta = -0.5.
    assert row["delta"] == pytest.approx(-0.5)


@pytest.mark.asyncio
async def test_operator_attribution_empty_without_qrels(tmp_path: Path) -> None:
    """Without persisted qrels, results are honestly not_applicable -- never fabricated."""
    db_path = tmp_path / "no_qrels.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(RUN_ID, "no-qrels-test", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_trace_v2(_trace("q0", filter_drops=True))

    registry = DbRegistry([str(db_path)])
    app = create_app(registry=registry, enable_uploads=False)
    client = TestClient(app)
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/operator-attribution?metric=recall&k=10")
    assert resp.status_code == 200
    rows = resp.json()
    filter_rows = [r for r in rows if r["op_id"] == "filter_cap"]
    assert filter_rows
    assert filter_rows[0]["result_status"] == "not_applicable"
    assert filter_rows[0]["delta"] is None
