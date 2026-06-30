from __future__ import annotations

import pytest

from retrieval_observatory.tracing.lift import lift_pipeline_result
from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


def _doc(doc_id: str, score: float, rank: int) -> Document:
    return Document(id=doc_id, text="", score=score, rank=rank)


def test_lift_single_source() -> None:
    snap = StageSnapshot(stage_index=0, stage_id="bm25", documents=[_doc("d1", 1.0, 1)], latency_ms=10.0)
    result = PipelineResult(query_id="q1", pipeline_id="p1", snapshots=[snap], total_latency_ms=10.0, status="OK")
    trace = lift_pipeline_result(result, run_id="run1")
    assert isinstance(trace, RetrievalTraceV2)
    assert trace.run_id == "run1"
    assert len(trace.spans) == 1
    assert trace.spans[0].op_type == "SOURCE"
    assert [c.doc_id for c in trace.spans[-1].outputs] == ["d1"]


def test_lift_fused_with_arm_spans() -> None:
    fused = StageSnapshot(
        stage_index=0,
        stage_id="rrf_fuse",
        documents=[_doc("d1", 1.0, 1)],
        latency_ms=4.0,
        arms=[
            StageSnapshot(stage_index=0, stage_id="bm25_arm", documents=[_doc("d1", 0.7, 1)], latency_ms=2.0),
            StageSnapshot(stage_index=0, stage_id="dense_arm", documents=[_doc("d2", 0.6, 1)], latency_ms=2.0),
        ],
    )
    rerank = StageSnapshot(stage_index=1, stage_id="rerank", documents=[_doc("d1", 1.5, 1)], latency_ms=6.0)
    result = PipelineResult(query_id="qf", pipeline_id="pf", snapshots=[fused, rerank], total_latency_ms=10.0, status="OK")
    trace = lift_pipeline_result(result, run_id="runf")
    assert len(trace.spans) == 4
    assert trace.spans[-1].op_type == "RERANK"
    assert trace.spans[-1].parent_ids


@pytest.mark.asyncio
async def test_round_trip_store(tmp_path) -> None:
    from retrieval_observatory.store.sqlite import SQLiteStore

    db_path = str(tmp_path / "trace_v2.db")
    store = SQLiteStore(db_path=db_path)
    await store.init_db()

    snap = StageSnapshot(stage_index=0, stage_id="bm25", documents=[_doc("d1", 1.0, 1)], latency_ms=10.0)
    result = PipelineResult(query_id="q1", pipeline_id="p1", snapshots=[snap], total_latency_ms=10.0, status="OK")
    trace = lift_pipeline_result(result, run_id="run1")
    await store.save_trace_v2(trace)

    loaded = await store.get_trace_v2(trace.trace_id)
    assert loaded is not None
    assert loaded.run_id == "run1"
    assert loaded.query_id == "q1"
    assert [c.doc_id for c in loaded.spans[-1].outputs] == ["d1"]
