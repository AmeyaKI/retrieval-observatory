from __future__ import annotations

import pytest

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def _span(op_id: str, op_type: str, parents: list[str], status: str = "FIRED") -> OperatorSpan:
    return OperatorSpan(
        op_id=op_id,
        op_type=op_type,  # type: ignore[arg-type]
        op_name=op_id,
        parent_ids=parents,
        status=status,  # type: ignore[arg-type]
        deterministic=True,
        replay_policy="EXACT",
        latency_ms=1.0,
        outputs=[Candidate(doc_id="d", score=1.0, rank=1, origin_op_ids=[op_id])],
    )


def _trace(trace_id: str, spans: list[OperatorSpan], *, status: str = "OK", final_op_ids: tuple[str, ...] = ()):
    return RetrievalTrace(
        trace_id=trace_id,
        service_id="svc",
        run_id="run",
        query_id=trace_id,
        query_text="q",
        pipeline_id="conditional",
        spans=spans,
        timing=TraceTiming(2.0, 2.0, 2.0),
        status=status,  # type: ignore[arg-type]
        final_op_ids=final_op_ids,
    )


def test_run_union_includes_conditional_and_error_only_topology():
    fast = _trace(
        "fast",
        [_span("source", "SOURCE", []), _span("fast", "RERANK", ["source"])],
        final_op_ids=("fast",),
    )
    slow_error = _trace(
        "slow",
        [
            _span("source", "SOURCE", []),
            _span("slow", "RERANK", ["source"], status="ERROR"),
            _span("error_reporter", "TRANSFORM", ["slow"], status="ERROR"),
        ],
        status="ERROR",
        final_op_ids=("slow",),
    )

    graph = build_pipeline_graphs({}, [fast, slow_error])[0]
    by_id = {node.node_id: node for node in graph.nodes}

    assert graph.contract_version == 2
    assert graph.projection_mode == "run_union"
    assert graph.trace_count == 2
    assert graph.complete_trace_count == 1
    assert graph.status_counts == {"OK": 1, "ERROR": 1}
    assert set(by_id) == {"source", "fast", "slow", "error_reporter"}
    assert by_id["fast"].trace_coverage == 0.5
    assert by_id["slow"].status_counts == {"ERROR": 1}
    assert by_id["slow"].fire_rate == 0.0
    assert set(graph.final_output_ids) == {"fast", "slow"}

    edges = {(edge.source, edge.target): edge for edge in graph.edges}
    assert edges[("source", "fast")].conditional is True
    assert edges[("source", "slow")].conditional is True
    assert edges[("slow", "error_reporter")].observed_count == 1


def test_exact_trace_projection_does_not_include_other_branch():
    fast = _trace(
        "fast",
        [_span("source", "SOURCE", []), _span("fast", "RERANK", ["source"])],
        final_op_ids=("fast",),
    )
    slow = _trace(
        "slow",
        [_span("source", "SOURCE", []), _span("slow", "RERANK", ["source"])],
        final_op_ids=("slow",),
    )

    graph = build_pipeline_graphs({}, [fast, slow], projection_mode="trace", trace_id="fast")[0]
    assert graph.projection_mode == "trace"
    assert graph.trace_count == 1
    assert {node.node_id for node in graph.nodes} == {"source", "fast"}


def test_exact_trace_projection_requires_identity_when_ambiguous():
    traces = [_trace("one", [_span("source", "SOURCE", [])]), _trace("two", [_span("source", "SOURCE", [])])]
    with pytest.raises(ValueError, match="trace_id"):
        build_pipeline_graphs({}, traces, projection_mode="trace")


def test_missing_parent_is_warned_and_not_rendered_as_an_edge():
    with pytest.raises(ValueError, match="unknown parent"):
        _trace("broken", [_span("child", "RERANK", ["missing"])], final_op_ids=("child",))


@pytest.mark.asyncio
async def test_conditional_operator_metric_identity_uses_run_union_layout():
    fast = _trace(
        "fast",
        [_span("source", "SOURCE", []), _span("fast", "RERANK", ["source"])],
        final_op_ids=("fast",),
    )
    slow = _trace(
        "slow",
        [_span("source", "SOURCE", []), _span("slow", "RERANK", ["source"])],
        final_op_ids=("slow",),
    )
    rows: list[dict] = []

    class _Store:
        async def save_metrics_batch(self, values):
            rows.extend(values)

    engine = MetricsEngine(recall_at_k_values=[1], ndcg_at_k_values=[], compute_mrr=False, compute_map=False)
    await engine.compute_from_traces("run", _Store(), [fast, slow], {"fast": {"d"}, "slow": {"d"}})

    quality_rows = [row for row in rows if row["metric_name"] == "recall" and row["stage_index"] == 1]
    assert {(row["query_id"], row["branch_id"]) for row in quality_rows} == {
        ("fast", "fast"),
        ("slow", "slow"),
    }
