from __future__ import annotations

import pytest

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming
from retrieval_observatory.tracing.replay import attribute_miss, without_operator


def _trace() -> RetrievalTrace:
    source = OperatorSpan(
        op_id="source",
        op_type="SOURCE",
        op_name="bm25",
        parent_ids=[],
        status="FIRED",
        deterministic=True,
        replay_policy="EXACT",
        latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["source"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["source"]),
        ],
    )
    rerank = OperatorSpan(
        op_id="rerank",
        op_type="RERANK",
        op_name="rerank",
        parent_ids=["source"],
        status="FIRED",
        deterministic=False,
        replay_policy="OBSERVED_ABLATION",
        latency_ms=1.0,
        outputs=[Candidate(doc_id="d2", score=1.1, rank=1, origin_op_ids=["rerank"])],
    )
    return RetrievalTrace(
        trace_id="t1",
        service_id="svc",
        run_id="run1",
        query_id="q1",
        query_text="q",
        pipeline_id="p1",
        spans=[source, rerank],
        timing=TraceTiming(2.0, 2.0, 2.0),
        final_op_ids=("rerank",),
    )


def _fused_trace() -> RetrievalTrace:
    arm_a = OperatorSpan(
        op_id="arm_bm25", op_type="SOURCE", op_name="bm25",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["arm_bm25"]),
            Candidate(doc_id="d2", score=0.5, rank=2, origin_op_ids=["arm_bm25"]),
        ],
    )
    arm_b = OperatorSpan(
        op_id="arm_dense", op_type="SOURCE", op_name="dense",
        parent_ids=[], status="FIRED", deterministic=False,
        replay_policy="NOT_REPLAYABLE", latency_ms=2.0,
        outputs=[
            Candidate(doc_id="d2", score=0.9, rank=1, origin_op_ids=["arm_dense"]),
            Candidate(doc_id="d3", score=0.8, rank=2, origin_op_ids=["arm_dense"]),
        ],
    )
    fuse = OperatorSpan(
        op_id="fuse_rrf", op_type="FUSE", op_name="rrf",
        parent_ids=["arm_bm25", "arm_dense"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=0.5,
        params={"k": 60},
        outputs=[
            Candidate(doc_id="d2", score=2.0, rank=1, origin_op_ids=["arm_bm25", "arm_dense"]),
            Candidate(doc_id="d1", score=1.0, rank=2, origin_op_ids=["arm_bm25"]),
            Candidate(doc_id="d3", score=0.8, rank=3, origin_op_ids=["arm_dense"]),
        ],
    )
    return RetrievalTrace(
        trace_id="t_fused", service_id="svc", run_id="run1", query_id="q1",
        query_text="q", pipeline_id="p1",
        spans=[arm_a, arm_b, fuse],
        timing=TraceTiming(3.5, 3.5, 3.5),
        final_op_ids=("fuse_rrf",),
    )


def test_without_operator_removes_downstream_docs() -> None:
    trace = _trace()
    cf = without_operator(trace, "source")
    assert all(c.doc_id != "d1" for span in cf.spans for c in span.outputs)


def test_without_operator_rerank_restores_inputs() -> None:
    trace = _trace()
    cf = without_operator(trace, "rerank")
    assert len(cf.spans) == 1
    assert cf.spans[0].op_id == "source"


def test_without_fuse_arm_recomputes_rrf() -> None:
    trace = _fused_trace()
    cf = without_operator(trace, "arm_bm25")
    fuse_cf = next(s for s in cf.spans if s.op_type == "FUSE")
    cf_doc_ids = [c.doc_id for c in fuse_cf.outputs]
    assert "d1" not in cf_doc_ids
    assert "d2" in cf_doc_ids
    assert "d3" in cf_doc_ids


def test_without_fuse_arm_removes_arm_span() -> None:
    trace = _fused_trace()
    cf = without_operator(trace, "arm_bm25")
    assert not any(s.op_id == "arm_bm25" for s in cf.spans)


def test_without_operator_dag_propagation() -> None:
    """B2: both children of removed op get counterfactual outputs."""
    source = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    child_a = OperatorSpan(
        op_id="filter_a", op_type="FILTER", op_name="filter_a",
        parent_ids=["src"], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=0.5,
        inputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    child_b = OperatorSpan(
        op_id="filter_b", op_type="FILTER", op_name="filter_b",
        parent_ids=["src"], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=0.5,
        inputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    trace = RetrievalTrace(
        trace_id="t_dag", service_id="svc", run_id="r", query_id="q",
        query_text="q", pipeline_id="p",
        spans=[source, child_a, child_b],
        timing=TraceTiming(2.0, 2.0, 2.0),
        final_op_ids=("filter_a", "filter_b"),
    )
    cf = without_operator(trace, "src")
    for span in cf.spans:
        assert len(span.outputs) == 0, f"Span {span.op_id} should have empty outputs"


@pytest.mark.asyncio
async def test_attribute_miss_reports_dropped_doc() -> None:
    trace = _trace()
    misses = await attribute_miss(trace, qrels={"q1": {"d1": 1, "d2": 1}}, k=1)
    assert any(miss.doc_id == "d1" for miss in misses)


@pytest.mark.asyncio
async def test_attribute_miss_never_retrieved() -> None:
    trace = _trace()
    misses = await attribute_miss(trace, qrels={"q1": {"d_missing": 1}}, k=10)
    assert len(misses) == 1
    assert misses[0].miss_type == "never_retrieved"


@pytest.mark.asyncio
async def test_attribute_miss_with_edge_store() -> None:
    from retrieval_observatory.store.sqlite import SQLiteStore
    from retrieval_observatory.corpus.graph import EdgeStore
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        edge_store = EdgeStore(store)
        await edge_store.add_edge("d1", "d_gold", "entity_link")

        trace = _trace()
        misses = await attribute_miss(
            trace, qrels={"q1": {"d_gold": 1}}, k=10, edge_store=edge_store
        )
        reachable_misses = [m for m in misses if m.miss_type == "gate_blocked"]
        assert len(reachable_misses) == 1


def _rerank_demotion_trace() -> RetrievalTrace:
    return _trace()  # existing helper: source (d1, d2) -> rerank keeps only d2


def _fusion_dilution_trace() -> RetrievalTrace:
    arm_a = OperatorSpan(
        op_id="arm_bm25", op_type="SOURCE", op_name="bm25",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["arm_bm25"]),
            Candidate(doc_id="d3", score=0.5, rank=2, origin_op_ids=["arm_bm25"]),
        ],
    )
    arm_b = OperatorSpan(
        op_id="arm_dense", op_type="SOURCE", op_name="dense",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d2", score=0.9, rank=1, origin_op_ids=["arm_dense"])],
    )
    fuse = OperatorSpan(
        op_id="fuse", op_type="FUSE", op_name="rrf",
        parent_ids=["arm_bm25", "arm_dense"], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=2.0, rank=1, origin_op_ids=["arm_bm25"])],
    )
    return RetrievalTrace(
        trace_id="t2", service_id="svc", run_id="run1", query_id="q1", query_text="q",
        pipeline_id="p1", spans=[arm_a, arm_b, fuse], timing=TraceTiming(3.0, 3.0, 3.0),
        final_op_ids=("fuse",),
    )


def _generation_ignored_context_trace() -> RetrievalTrace:
    retrieve = OperatorSpan(
        op_id="retrieve", op_type="SOURCE", op_name="bm25",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["retrieve"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["retrieve"]),
        ],
    )
    generate = OperatorSpan(
        op_id="generate", op_type="GENERATE", op_name="answer_synthesis",
        parent_ids=["retrieve"], status="FIRED", deterministic=False,
        replay_policy="NOT_REPLAYABLE", latency_ms=5.0,
        inputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["retrieve"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["retrieve"]),
        ],
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["retrieve"])],
    )
    return RetrievalTrace(
        trace_id="t3", service_id="svc", run_id="run1", query_id="q1", query_text="q",
        pipeline_id="p1", spans=[retrieve, generate], timing=TraceTiming(6.0, 6.0, 6.0),
        final_op_ids=("generate",),
    )


@pytest.mark.asyncio
async def test_attribute_miss_classifies_rerank_demotion() -> None:
    trace = _rerank_demotion_trace()
    misses = await attribute_miss(trace, qrels={"q1": {"d1": 1, "d2": 1}}, k=1)
    assert misses[0].doc_id == "d1"
    assert misses[0].miss_type == "rerank_demotion"
    assert misses[0].op_id == "rerank"


@pytest.mark.asyncio
async def test_attribute_miss_classifies_fusion_dilution() -> None:
    trace = _fusion_dilution_trace()
    misses = await attribute_miss(trace, qrels={"q1": {"d1": 1, "d2": 1, "d3": 1}}, k=1)
    by_doc = {m.doc_id: m for m in misses}
    assert by_doc["d2"].miss_type == "fusion_dilution"
    assert by_doc["d2"].op_id == "fuse"
    assert by_doc["d3"].miss_type == "fusion_dilution"


@pytest.mark.asyncio
async def test_attribute_miss_classifies_generation_ignored_context() -> None:
    trace = _generation_ignored_context_trace()
    misses = await attribute_miss(trace, qrels={"q1": {"d1": 1, "d2": 1}}, k=1)
    assert misses[0].doc_id == "d2"
    assert misses[0].miss_type == "generation_ignored_context"
    assert misses[0].op_id == "generate"


def test_without_boost_restores_pre_boost_scores() -> None:
    source = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    boost = OperatorSpan(
        op_id="boost", op_type="BOOST", op_name="recency_boost",
        parent_ids=["src"], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=0.1,
        inputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
        outputs=[Candidate(
            doc_id="d1", score=1.5, rank=1, origin_op_ids=["src"],
            score_components={"pre_boost": 1.0, "boost": 0.5},
        )],
    )
    trace = RetrievalTrace(
        trace_id="t_boost", service_id="svc", run_id="r", query_id="q",
        query_text="q", pipeline_id="p",
        spans=[source, boost],
        timing=TraceTiming(1.1, 1.1, 1.1),
        final_op_ids=("boost",),
    )
    cf = without_operator(trace, "boost")
    assert len(cf.spans) == 1
    assert cf.spans[0].op_id == "src"


def test_without_gate_passes_through() -> None:
    gate = OperatorSpan(
        op_id="gate", op_type="GATE", op_name="intent",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="NOT_REPLAYABLE", latency_ms=0.1,
        gate_values={"intent": "navigational"},
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1)],
    )
    source = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25",
        parent_ids=["gate"], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    trace = RetrievalTrace(
        trace_id="t_gate", service_id="svc", run_id="r", query_id="q",
        query_text="q", pipeline_id="p",
        spans=[gate, source],
        timing=TraceTiming(1.1, 1.1, 1.1),
        final_op_ids=("src",),
    )
    cf = without_operator(trace, "gate")
    assert len(cf.spans) == 1
    assert cf.spans[0].op_id == "src"
