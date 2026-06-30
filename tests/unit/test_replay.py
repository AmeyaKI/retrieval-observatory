from __future__ import annotations

from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
from retrieval_observatory.tracing.replay import attribute_miss, without_operator


def _trace() -> RetrievalTraceV2:
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
    return RetrievalTraceV2(
        trace_id="t1",
        run_id="run1",
        query_id="q1",
        query_text="q",
        pipeline_id="p1",
        spans=[source, rerank],
        total_latency_ms=2.0,
    )


def test_without_operator_removes_downstream_docs() -> None:
    trace = _trace()
    cf = without_operator(trace, "source")
    assert all(c.doc_id != "d1" for span in cf.spans for c in span.outputs)


def test_attribute_miss_reports_dropped_doc() -> None:
    trace = _trace()
    misses = attribute_miss(trace, qrels={"q1": {"d1": 1, "d2": 1}}, k=1)
    assert any(miss.doc_id == "d1" for miss in misses)
