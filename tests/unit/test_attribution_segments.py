from __future__ import annotations

from retrieval_observatory.tracing.attribution import operator_marginal_contribution, segment_key
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2


def _trace(query_id: str, fired: bool) -> RetrievalTraceV2:
    gate = OperatorSpan(
        op_id="gate_a",
        op_type="GATE",
        op_name="intent_gate",
        parent_ids=[],
        status="FIRED" if fired else "SKIPPED_BY_GATE",
        deterministic=True,
        replay_policy="NOT_REPLAYABLE",
        latency_ms=1.0,
        gate_values={"intent": "navigational" if fired else "other"},
    )
    source = OperatorSpan(
        op_id="source_a",
        op_type="SOURCE",
        op_name="bm25",
        parent_ids=[gate.op_id],
        status="FIRED",
        deterministic=True,
        replay_policy="EXACT",
        latency_ms=3.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["source_a"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["source_a"]),
        ],
    )
    return RetrievalTraceV2(
        trace_id=f"t_{query_id}",
        run_id="run1",
        query_id=query_id,
        query_text="q",
        pipeline_id="p",
        spans=[gate, source],
        total_latency_ms=4.0,
    )


def test_segment_key_baseline_when_no_gate_values() -> None:
    trace = _trace("q1", fired=True)
    trace.spans[0].gate_values = {}
    assert segment_key(trace) == "baseline"


def test_fired_subset_only() -> None:
    traces = [_trace("q1", fired=True), _trace("q2", fired=False)]
    qrels = {"q1": {"d1": 1}, "q2": {"d1": 1}}
    rows = operator_marginal_contribution(traces, op_id="source_a", qrels=qrels, metric="recall", k=1)
    assert rows
    assert any(r.result_status in {"measured", "not_applicable"} for r in rows)


def test_ndcg_metric_supported() -> None:
    traces = [_trace("q1", fired=True)]
    qrels = {"q1": {"d1": 2, "d2": 1}}
    rows = operator_marginal_contribution(traces, op_id="source_a", qrels=qrels, metric="ndcg", k=2)
    assert rows
    assert rows[0].metric == "ndcg"


def test_bootstrap_ci_when_enough_pairs() -> None:
    traces = [_trace(f"q{i}", fired=True) for i in range(25)]
    qrels = {f"q{i}": {"d1": 1, "d2": 1} for i in range(25)}
    rows = operator_marginal_contribution(
        traces, op_id="source_a", qrels=qrels, metric="recall", k=1, n_power_threshold=20
    )
    measured = [r for r in rows if r.result_status == "measured"]
    assert measured
    assert measured[0].ci_low is not None
    assert measured[0].ci_high is not None
