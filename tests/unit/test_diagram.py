"""Trace-native diagram JSON (PipelineGraph contract) + standalone HTML export."""
from retrieval_observatory.diagram.html import render_diagram_html
from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2


def _agg_entry(pipeline_id, stage_index, metric_name, k, mean, ci, branch_id=None):
    return {
        "pipeline_id": pipeline_id,
        "stage_index": stage_index,
        "metric_name": metric_name,
        "k": k,
        "branch_id": branch_id,
        "mean": mean,
        "ci_low": ci[0],
        "ci_high": ci[1],
    }


def _linear_trace() -> RetrievalTraceV2:
    source = OperatorSpan(
        op_id="stage0_bm25", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d", score=1.0, rank=1, origin_op_ids=["stage0_bm25"])],
    )
    return RetrievalTraceV2(
        trace_id="t1", run_id="r", query_id="q1", query_text="q", pipeline_id="p",
        spans=[source], total_latency_ms=1.0, final_op_id="stage0_bm25",
    )


def _fusion_trace() -> RetrievalTraceV2:
    arm_a = OperatorSpan(
        op_id="arm_a", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["arm_a"])],
    )
    arm_b = OperatorSpan(
        op_id="arm_b", op_type="SOURCE", op_name="dense", parent_ids=[],
        status="FIRED", deterministic=False, replay_policy="NOT_REPLAYABLE", latency_ms=1.0,
        outputs=[Candidate(doc_id="d2", score=0.9, rank=1, origin_op_ids=["arm_b"])],
    )
    fuse = OperatorSpan(
        op_id="fuse", op_type="FUSE", op_name="rrf", parent_ids=["arm_a", "arm_b"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=0.5, rank=1, origin_op_ids=["arm_a"]),
            Candidate(doc_id="d2", score=0.4, rank=2, origin_op_ids=["arm_b"]),
        ],
    )
    return RetrievalTraceV2(
        trace_id="t2", run_id="r", query_id="q2", query_text="q", pipeline_id="p_fused",
        spans=[arm_a, arm_b, fuse], total_latency_ms=2.0, final_op_id="fuse",
    )


def test_build_pipeline_graphs_surfaces_ci():
    metrics = {
        "p|stage0_bm25|recall@10": _agg_entry("p", 0, "recall", 10, 0.7, (0.6, 0.8)),
        "p|stage0_bm25|ndcg@10": _agg_entry("p", 0, "ndcg", 10, 0.5, (0.4, 0.6)),
        "p|stage0_bm25|latency_p50": _agg_entry("p", 0, "latency_p50", 0, 12.0, (10.0, 14.0)),
    }
    graphs = build_pipeline_graphs(metrics, [_linear_trace()])
    assert len(graphs) == 1
    node = graphs[0].nodes[0].to_dict()
    recall = node["metrics"]["recall"]
    assert recall["ci_low"] < recall["mean"] < recall["ci_high"]
    assert recall["k"] == 10
    assert node["metrics"]["ndcg@10"]["ci_low"] == 0.4


def test_build_pipeline_graphs_fan_in_edge():
    metrics = {
        "p_fused|fuse|recall@10": _agg_entry("p_fused", 1, "recall", 10, 0.5, (0.3, 0.7)),
    }
    graphs = build_pipeline_graphs(metrics, [_fusion_trace()])
    graph = graphs[0]
    fan_in_edges = [e for e in graph.edges if e.kind == "fan_in"]
    assert len(fan_in_edges) == 2  # arm_a->fuse, arm_b->fuse
    merge_nodes = [n for n in graph.nodes if n.is_merge]
    assert len(merge_nodes) == 1
    assert merge_nodes[0].node_id == "fuse"


def test_render_html_is_standalone():
    metrics = {
        "p|stage0_bm25|recall@10": _agg_entry("p", 0, "recall", 10, 0.7, (0.6, 0.8)),
    }
    graphs = build_pipeline_graphs(metrics, [_linear_trace()])
    pipelines = [g.to_dict() for g in graphs]
    html = render_diagram_html("run123", pipelines)
    assert "<html" in html and "</html>" in html
    assert "95% CI" in html
    assert "run123" in html
    # No external network resources — fully offline artifact.
    assert "http://" not in html and "https://" not in html


def test_render_html_fan_in_uses_distinct_edge_class():
    metrics = {
        "p_fused|fuse|recall@10": _agg_entry("p_fused", 1, "recall", 10, 0.5, (0.3, 0.7)),
    }
    graphs = build_pipeline_graphs(metrics, [_fusion_trace()])
    pipelines = [g.to_dict() for g in graphs]
    html = render_diagram_html("run456", pipelines)
    assert "edge-fan-in" in html
    assert "is-merge" in html


def test_render_html_empty_pipelines_no_crash():
    html = render_diagram_html("run789", [])
    assert "No pipelines to display" in html
