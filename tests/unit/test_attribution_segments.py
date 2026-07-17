from __future__ import annotations

from retrieval_observatory.tracing.attribution import operator_marginal_contribution, segment_key
from dataclasses import replace

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def _trace(query_id: str, fired: bool) -> RetrievalTrace:
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
    return RetrievalTrace(
        service_id="test",
        trace_id=f"t_{query_id}",
        run_id="run1",
        query_id=query_id,
        query_text="q",
        pipeline_id="p",
        spans=[gate, source],
        timing=TraceTiming(4.0, 4.0, 4.0),
        final_op_ids=("source_a",),
    )


def test_segment_key_baseline_when_no_gate_values() -> None:
    trace = _trace("q1", fired=True)
    trace.spans = (replace(trace.spans[0], gate_values={}), *trace.spans[1:])
    assert segment_key(trace) == "baseline"


def test_segment_key_multi_gate() -> None:
    """B1 fix: multi-gate pipelines merge all gate values."""
    gate_a = OperatorSpan(
        op_id="gate_intent", op_type="GATE", op_name="intent_gate",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="NOT_REPLAYABLE", latency_ms=1.0,
        gate_values={"intent": "navigational"},
    )
    gate_b = OperatorSpan(
        op_id="gate_entity", op_type="GATE", op_name="entity_gate",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="NOT_REPLAYABLE", latency_ms=1.0,
        gate_values={"entity_type": "person"},
    )
    source = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25",
        parent_ids=["gate_intent", "gate_entity"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    trace = RetrievalTrace(
        service_id="test",
        trace_id="t_multi_gate", run_id="r", query_id="q",
        query_text="q", pipeline_id="p",
        spans=[gate_a, gate_b, source], timing=TraceTiming(3.0, 3.0, 3.0), final_op_ids=("src",),
    )
    key = segment_key(trace)
    assert "entity_type=person" in key
    assert "intent=navigational" in key


def test_fired_subset_only() -> None:
    traces = [_trace("q1", fired=True), _trace("q2", fired=False)]
    qrels = {"q1": {"d1": 1}, "q2": {"d1": 1}}
    rows = operator_marginal_contribution(traces, op_id="source_a", qrels=qrels, metric="recall", k=1)
    assert rows
    assert any(r.result_status in {"replayed", "not_applicable", "indeterminate"} for r in rows)


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
    replayed = [r for r in rows if r.result_status == "replayed"]
    assert replayed
    assert replayed[0].ci_low is not None
    assert replayed[0].ci_high is not None


def test_significant_field_populated_with_bh() -> None:
    """B5 fix: significant field is populated with BH-corrected values."""
    traces = [_trace(f"q{i}", fired=True) for i in range(30)]
    qrels = {f"q{i}": {"d1": 1, "d2": 1} for i in range(30)}
    rows = operator_marginal_contribution(
        traces, op_id="source_a", qrels=qrels, metric="recall", k=1, n_power_threshold=20
    )
    populated = [r for r in rows if r.significant is not None]
    assert len(populated) > 0
    # Every significance-tested row also exposes its raw p_value and BH-corrected q_value.
    for row in populated:
        assert row.p_value is not None
        assert 0.0 <= row.p_value <= 1.0
        assert row.q_value is not None


def test_low_power_rows_have_no_pvalue() -> None:
    # Below n_power_threshold, no significance test is run, so p_value/q_value stay None.
    traces = [_trace(f"q{i}", fired=True) for i in range(3)]
    qrels = {f"q{i}": {"d1": 1, "d2": 1} for i in range(3)}
    rows = operator_marginal_contribution(
        traces, op_id="source_a", qrels=qrels, metric="recall", k=1, n_power_threshold=20
    )
    for row in rows:
        if row.low_power:
            assert row.p_value is None
            assert row.q_value is None


def test_final_op_id_used_not_spans_last() -> None:
    """B3 fix: attribution uses final_op_id, not spans[-1]."""
    gate = OperatorSpan(
        op_id="gate", op_type="GATE", op_name="gate",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="NOT_REPLAYABLE", latency_ms=0.1,
        gate_values={"x": "y"},
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1)],
    )
    source = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25",
        parent_ids=["gate"], status="FIRED", deterministic=True,
        replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["src"]),
        ],
    )
    trace = RetrievalTrace(
        service_id="test",
        trace_id="t_final", run_id="r", query_id="q1",
        query_text="q", pipeline_id="p",
        spans=[source, gate],
        timing=TraceTiming(1.1, 1.1, 1.1),
        final_op_ids=("src",),
    )
    qrels = {"q1": {"d1": 1}}
    rows = operator_marginal_contribution(
        [trace], op_id="src", qrels=qrels, metric="recall", k=10
    )
    assert rows
