from __future__ import annotations

from retrieval_observatory.tracing.attribution import operator_marginal_contribution
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
from retrieval_observatory.tracing.replay import simulate_without_operator


def _span(op_id: str, op_type: str, parents: list[str], policy: str, docs: list[str]) -> OperatorSpan:
    candidates = [
        Candidate(doc_id=doc_id, score=1.0 / rank, rank=rank, origin_op_ids=["source"])
        for rank, doc_id in enumerate(docs, start=1)
    ]
    return OperatorSpan(
        op_id=op_id,
        op_type=op_type,  # type: ignore[arg-type]
        op_name=op_id,
        parent_ids=parents,
        status="FIRED",
        deterministic=policy == "EXACT",
        replay_policy=policy,  # type: ignore[arg-type]
        latency_ms=1.0,
        inputs=list(candidates),
        outputs=list(candidates),
    )


def _trace(*spans: OperatorSpan) -> RetrievalTraceV2:
    return RetrievalTraceV2(
        trace_id="trace",
        run_id="run",
        query_id="q",
        query_text="query",
        pipeline_id="pipeline",
        spans=list(spans),
        total_latency_ms=float(len(spans)),
        final_op_id=spans[-1].op_id,
    )


def test_not_replayable_target_has_no_projected_trace() -> None:
    source = _span("source", "SOURCE", [], "NOT_REPLAYABLE", ["gold"])

    result = simulate_without_operator(_trace(source), "source")

    assert result.status == "indeterminate"
    assert result.evidence_class == "unavailable"
    assert result.trace is None
    assert "NOT_REPLAYABLE" in (result.reason or "")


def test_unsupported_descendant_blocks_numeric_replay() -> None:
    source = _span("source", "SOURCE", [], "EXACT", ["gold"])
    generator = _span("generate", "GENERATE", ["source"], "NOT_REPLAYABLE", ["gold"])

    result = simulate_without_operator(_trace(source, generator), "source")

    assert result.status == "indeterminate"
    assert result.trace is None
    assert result.unsupported_descendants == ["generate"]


def test_supported_projection_reconnects_parents_and_marks_timing_unavailable() -> None:
    source = _span("source", "SOURCE", [], "EXACT", ["gold", "other"])
    rerank = _span("rerank", "RERANK", ["source"], "OBSERVED_ABLATION", ["other"])
    result = simulate_without_operator(_trace(source, rerank), "rerank")

    assert result.status == "replayed"
    assert result.trace is not None
    assert result.trace.final_op_id == "source"
    assert result.trace.total_latency_ms == 0.0
    assert result.trace.metadata["replay_timing"].startswith("unavailable")


def test_indeterminate_attribution_never_has_numeric_statistics() -> None:
    source = _span("source", "SOURCE", [], "NOT_REPLAYABLE", ["gold"])
    traces = [_trace(source) for _ in range(25)]
    for index, trace in enumerate(traces):
        trace.trace_id = f"trace-{index}"
        trace.query_id = f"q-{index}"
    qrels = {trace.query_id: {"gold": 1} for trace in traces}

    row = operator_marginal_contribution(traces, "source", qrels, n_power_threshold=20)[0]

    assert row.result_status == "indeterminate"
    assert row.evidence_class == "unavailable"
    assert row.delta is None
    assert row.ci_low is None
    assert row.ci_high is None
    assert row.p_value is None
    assert row.q_value is None
    assert row.significant is None
