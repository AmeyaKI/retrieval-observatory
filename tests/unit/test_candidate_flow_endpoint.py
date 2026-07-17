from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming
from retrieval_observatory.types import Query

RUN_ID = "run1"


def _trace() -> RetrievalTrace:
    """SOURCE(d1,d2) -> FILTER drops d2."""
    source = OperatorSpan(
        op_id="source_bm25", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["source_bm25"]),
            Candidate(
                doc_id="d2",
                score=0.9,
                rank=2,
                origin_op_ids=["source_bm25"],
                metadata={"preview": "lost relevant chunk about taxes"},
            ),
        ],
    )
    filt = OperatorSpan(
        op_id="filter_cap", op_type="FILTER", op_name="cap", parent_ids=["source_bm25"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        input_groups={"source_bm25": tuple(source.outputs)}, outputs=[source.outputs[0]],
    )
    return RetrievalTrace(
        service_id="test",
        trace_id="t_q0", run_id=RUN_ID, query_id="q0", query_text="q",
        pipeline_id="p", spans=[source, filt], timing=TraceTiming(2.0, 2.0, 2.0), final_op_ids=("filter_cap",),
    )


def _hybrid_trace() -> RetrievalTrace:
    """BM25∥dense → fuse → rerank drops relevant d_gold."""
    bm25 = OperatorSpan(
        op_id="bm25", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d_noise", score=1.0, rank=1, origin_op_ids=["bm25"]),
            Candidate(doc_id="d_gold", score=0.8, rank=2, origin_op_ids=["bm25"]),
        ],
    )
    dense = OperatorSpan(
        op_id="dense", op_type="SOURCE", op_name="dense", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d_gold", score=0.95, rank=1, origin_op_ids=["dense"]),
            Candidate(doc_id="d_other", score=0.5, rank=2, origin_op_ids=["dense"]),
        ],
    )
    fuse = OperatorSpan(
        op_id="fuse", op_type="FUSE", op_name="rrf", parent_ids=["bm25", "dense"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        input_groups={
            "bm25": tuple(bm25.outputs),
            "dense": tuple(dense.outputs),
        },
        outputs=[
            Candidate(doc_id="d_gold", score=0.9, rank=1, origin_op_ids=["bm25", "dense"]),
            Candidate(doc_id="d_noise", score=0.7, rank=2, origin_op_ids=["bm25"]),
            Candidate(doc_id="d_other", score=0.4, rank=3, origin_op_ids=["dense"]),
        ],
    )
    rerank = OperatorSpan(
        op_id="rerank", op_type="RERANK", op_name="ce", parent_ids=["fuse"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=5.0,
        input_groups={"fuse": tuple(fuse.outputs)},
        outputs=[
            Candidate(doc_id="d_noise", score=0.99, rank=1, origin_op_ids=["bm25"]),
            Candidate(doc_id="d_other", score=0.5, rank=2, origin_op_ids=["dense"]),
        ],
    )
    return RetrievalTrace(
        service_id="test",
        trace_id="t_hybrid", run_id=RUN_ID, query_id="q0", query_text="hybrid query",
        pipeline_id="hybrid", spans=[bm25, dense, fuse, rerank],
        timing=TraceTiming(8.0, 8.0, 8.0), final_op_ids=("rerank",),
    )


@pytest.fixture
async def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "flow.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(RUN_ID, "flow-test", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_trace(_trace())
    await store.save_qrels(RUN_ID, {"q0": {"d1": 1, "d2": 2}})
    await store.save_run_queries(
        RUN_ID,
        [Query(text="tax filing help", query_id="q0")],
        dataset_name="custom",
    )
    return db_path


@pytest.fixture
async def hybrid_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "hybrid_flow.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(RUN_ID, "hybrid-flow", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_trace(_hybrid_trace())
    await store.save_qrels(RUN_ID, {"q0": {"d_gold": 1}})
    await store.save_run_queries(
        RUN_ID,
        [Query(text="hybrid query", query_id="q0")],
        dataset_name="custom",
    )
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
    assert body["relevant"] is True
    assert body["grade"] == 2
    pipeline = body["pipelines"][0]
    hist = pipeline["history"]
    assert hist["introduced_at"] == "source_bm25"
    assert hist["dropped_at"] == "filter_cap"
    assert hist["dropped_reason"] == "filtered"
    assert hist["survived"] is False
    assert pipeline["drop_replay_assumptions"] is not None
    assert pipeline["drop_replay_assumptions"]["strategy"] == "filter_passthrough_inputs"


@pytest.mark.asyncio
async def test_survivor_candidate_flow(seeded_db: Path) -> None:
    registry = DbRegistry([str(seeded_db)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/queries/q0/candidates/d1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["relevant"] is True
    assert body["grade"] == 1
    hist = body["pipelines"][0]["history"]
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


@pytest.mark.asyncio
async def test_candidate_journeys_join_qrels(seeded_db: Path) -> None:
    registry = DbRegistry([str(seeded_db)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/queries/q0/candidate-journeys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_id"] == "q0"
    assert body["query_text"] == "tax filing help"
    by_doc = {row["doc_id"]: row for row in body["rows"]}
    assert "d2" in by_doc
    assert by_doc["d2"]["relevant"] is True
    assert by_doc["d2"]["grade"] == 2
    assert by_doc["d2"]["dropped_at"] == "filter_cap"
    assert by_doc["d2"]["drop_reason"] == "filtered"
    assert by_doc["d2"]["survived"] is False
    assert by_doc["d2"]["doc_preview"] == "lost relevant chunk about taxes"
    assert "d1" in by_doc
    assert by_doc["d1"]["survived"] is True
    assert by_doc["d1"]["dropped_at"] is None
    assert body["rows"][0]["doc_id"] == "d2"


@pytest.mark.asyncio
async def test_candidate_journeys_hybrid_rerank_drop(hybrid_db: Path) -> None:
    registry = DbRegistry([str(hybrid_db)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db_id = registry.list_db_ids()[0]

    resp = client.get(f"/dbs/{db_id}/runs/{RUN_ID}/queries/q0/candidate-journeys")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    gold = next(r for r in rows if r["doc_id"] == "d_gold")
    assert gold["relevant"] is True
    assert gold["introduced_at"] in {"bm25", "dense"}
    assert gold["dropped_at"] == "rerank"
    assert gold["drop_reason"] == "reranked_out"
    assert gold["survived"] is False
    assert gold["miss_type"] in {"rerank_demotion", "dropped_by_op", "ranked_below_k"}
