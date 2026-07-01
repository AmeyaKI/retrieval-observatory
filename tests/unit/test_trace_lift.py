from __future__ import annotations

import pytest

from retrieval_observatory.metrics.ranking import ndcg_at_k
from retrieval_observatory.metrics.recall import recall_at_k
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
    assert trace.final_op_id == trace.spans[0].op_id
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
    assert [span.op_type for span in trace.spans] == ["SOURCE", "SOURCE", "FUSE", "RERANK"]
    assert trace.spans[2].parent_ids == [trace.spans[0].op_id, trace.spans[1].op_id]
    assert trace.spans[-1].op_type == "RERANK"
    assert trace.spans[-1].parent_ids == [trace.spans[2].op_id]


def test_origin_op_ids_for_docs_in_multiple_fusion_arms() -> None:
    fused = StageSnapshot(
        stage_index=0,
        stage_id="rrf_fuse",
        documents=[_doc("shared", 1.0, 1), _doc("bm25_only", 0.5, 2)],
        latency_ms=4.0,
        arms=[
            StageSnapshot(
                stage_index=0,
                stage_id="bm25_arm",
                documents=[_doc("shared", 0.7, 1), _doc("bm25_only", 0.4, 2)],
                latency_ms=2.0,
            ),
            StageSnapshot(
                stage_index=0,
                stage_id="dense_arm",
                documents=[_doc("shared", 0.6, 1)],
                latency_ms=2.0,
            ),
        ],
    )
    result = PipelineResult(query_id="qf", pipeline_id="pf", snapshots=[fused], total_latency_ms=4.0, status="OK")

    trace = lift_pipeline_result(result, run_id="runf")

    fuse_span = trace.spans[-1]
    shared = next(candidate for candidate in fuse_span.outputs if candidate.doc_id == "shared")
    assert shared.origin_op_ids == [trace.spans[0].op_id, trace.spans[1].op_id]
    assert set(shared.score_components) == set(shared.origin_op_ids)


def test_lift_empty_result_marks_trace_error() -> None:
    result = PipelineResult(query_id="q-empty", pipeline_id="p", snapshots=[], total_latency_ms=0.0, status="OK")

    trace = lift_pipeline_result(result, run_id="run-empty")

    assert trace.status == "ERROR"
    assert trace.spans == []


def test_no_metric_change() -> None:
    """Metrics computed on PipelineResult docs must be bitwise-equal to metrics
    computed on the V2 trace's final span outputs."""
    relevant_ids = {"d1", "d3", "d5"}

    bm25_docs = [
        _doc("d1", 5.0, 1),
        _doc("d2", 4.5, 2),
        _doc("d3", 4.0, 3),
        _doc("d4", 3.5, 4),
        _doc("d5", 3.0, 5),
        _doc("d6", 2.5, 6),
        _doc("d7", 2.0, 7),
        _doc("d8", 1.5, 8),
    ]
    rerank_docs = [
        _doc("d3", 9.0, 1),
        _doc("d1", 8.5, 2),
        _doc("d6", 7.0, 3),
        _doc("d5", 6.5, 4),
        _doc("d2", 5.0, 5),
    ]

    bm25_snap = StageSnapshot(stage_index=0, stage_id="bm25_source", documents=bm25_docs, latency_ms=5.0)
    rerank_snap = StageSnapshot(stage_index=1, stage_id="rerank", documents=rerank_docs, latency_ms=15.0)

    result = PipelineResult(
        query_id="q-metric",
        pipeline_id="p-metric",
        snapshots=[bm25_snap, rerank_snap],
        total_latency_ms=20.0,
        status="OK",
    )

    final_doc_ids = [d.id for d in result.snapshots[-1].documents]
    expected_recall = recall_at_k(final_doc_ids, relevant_ids, k=10)
    expected_ndcg = ndcg_at_k(final_doc_ids, relevant_ids, k=10)

    trace = lift_pipeline_result(result, run_id="run-metric")
    trace_doc_ids = [c.doc_id for c in trace.spans[-1].outputs]

    actual_recall = recall_at_k(trace_doc_ids, relevant_ids, k=10)
    actual_ndcg = ndcg_at_k(trace_doc_ids, relevant_ids, k=10)

    assert expected_recall == actual_recall
    assert expected_ndcg == actual_ndcg


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
    assert loaded.final_op_id == trace.final_op_id
    assert [c.doc_id for c in loaded.spans[-1].outputs] == ["d1"]
