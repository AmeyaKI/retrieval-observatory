from retrieval_observatory.dashboard.api import (
    _compute_stage_contributions,
    _overview_warnings,
)
from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def test_overview_warnings_cache_and_zero_rate():
    metrics = {
        "dense|stage0|ndcg@10": {
            "pipeline_id": "dense_only",
            "stage_index": 0,
            "metric_name": "ndcg",
            "k": 10,
            "mean": 0.31,
            "ci_low": 0.28,
            "ci_high": 0.34,
            "n": 323,
            "zero_count": 99,
            "zero_pct": 30.7,
        },
        "dense|stage0|recall@1": {
            "pipeline_id": "dense_only",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 1,
            "mean": 0.04,
            "ci_low": 0.03,
            "ci_high": 0.05,
            "n": 323,
            "zero_count": 189,
            "zero_pct": 58.5,
        },
        "dense|stage0|latency_p50@0": {
            "pipeline_id": "dense_only",
            "stage_index": 0,
            "metric_name": "latency_p50",
            "k": 0,
            "mean": 4.8,
            "std": 0.0,
            "ci_low": 4.8,
            "ci_high": 4.8,
            "n": 323,
            "zero_pct": 0.0,
        },
    }
    manifest = {"cache_results": True, "dataset": {"missing_qrel_doc_ids": 0}}
    warnings = _overview_warnings(metrics, [], manifest)
    assert any("cache_results" in w for w in warnings)
    assert any("elevated zero-score" in w and "dense_only" in w for w in warnings)
    assert any("ndcg@10" in w for w in warnings)
    assert any("sparse confidence" in w or "wide or sparse" in w for w in warnings)


def test_pipeline_graph_reports_fused_arms():
    """Trace-native replacement for the deleted heuristic _pipeline_topology: a fused
    stage's arms are separate sibling nodes joined to the merge node by fan_in edges,
    not nested "arms" inside one card."""
    arm_bm25 = OperatorSpan(
        op_id="bm25_stage", op_type="SOURCE", op_name="bm25_stage", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=4.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["bm25_stage"])],
    )
    arm_dense = OperatorSpan(
        op_id="dense_stage", op_type="SOURCE", op_name="dense_stage", parent_ids=[],
        status="FIRED", deterministic=False, replay_policy="NOT_REPLAYABLE", latency_ms=6.0,
        outputs=[Candidate(doc_id="d2", score=0.9, rank=1, origin_op_ids=["dense_stage"])],
    )
    fused = OperatorSpan(
        op_id="fused", op_type="FUSE", op_name="fused", parent_ids=["bm25_stage", "dense_stage"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=10.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["bm25_stage"]),
            Candidate(doc_id="d2", score=0.8, rank=2, origin_op_ids=["dense_stage"]),
        ],
    )
    trace = RetrievalTrace(
        trace_id="t1", service_id="svc", run_id="r", query_id="q1", query_text="q", pipeline_id="fused__rerank",
        spans=[arm_bm25, arm_dense, fused], timing=TraceTiming(10.0, 10.0, 10.0), final_op_ids=("fused",),
    )
    metrics = {
        "fused__rerank|fused|ndcg@10": {
            "pipeline_id": "fused__rerank", "stage_index": 1, "metric_name": "ndcg",
            "k": 10, "mean": 0.4, "branch_id": None,
        },
        "fused__rerank|fused|recall@10": {
            "pipeline_id": "fused__rerank", "stage_index": 1, "metric_name": "recall",
            "k": 10, "mean": 0.6, "branch_id": None,
        },
        "fused__rerank|bm25_stage|recall@10": {
            "pipeline_id": "fused__rerank", "stage_index": 0, "metric_name": "recall",
            "k": 10, "mean": 0.3, "branch_id": None,
        },
    }
    graphs = build_pipeline_graphs(metrics, [trace])
    assert len(graphs) == 1
    graph = graphs[0]
    node_ids = {n.node_id for n in graph.nodes}
    assert {"bm25_stage", "fused"} <= node_ids
    fan_in = [e for e in graph.edges if e.kind == "fan_in"]
    assert any(e.source == "bm25_stage" and e.target == "fused" for e in fan_in)
    fused_node = next(n for n in graph.nodes if n.node_id == "fused")
    assert fused_node.is_merge is True


def test_stage_contributions_mark_arm_vs_fused_indeterminate_when_fused_zero_signal():
    metrics = {
        "hybrid|stage0|recall@10|branch=bm25_arm": {
            "pipeline_id": "hybrid",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.5,
            "branch_id": "bm25_arm",
        },
        "hybrid|stage0|recall@10": {
            "pipeline_id": "hybrid",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.0,
            "branch_id": None,
        },
    }
    metrics_rows = [
        {"query_id": "q1", "pipeline_id": "hybrid", "stage_index": 0, "branch_id": "bm25_arm", "metric_name": "recall", "k": 10, "value": 1.0},
        {"query_id": "q2", "pipeline_id": "hybrid", "stage_index": 0, "branch_id": "bm25_arm", "metric_name": "recall", "k": 10, "value": 0.0},
        {"query_id": "q1", "pipeline_id": "hybrid", "stage_index": 0, "branch_id": None, "metric_name": "recall", "k": 10, "value": 0.0},
        {"query_id": "q2", "pipeline_id": "hybrid", "stage_index": 0, "branch_id": None, "metric_name": "recall", "k": 10, "value": 0.0},
    ]
    contributions = _compute_stage_contributions(metrics, metrics_rows)
    arm = next(c for c in contributions if c["comparison_tier"] == "within_stage_arm")
    recall_delta = arm["deltas"]["recall@10"]
    assert arm["indeterminate"] is True
    assert recall_delta["indeterminate"] is True
    assert recall_delta["indeterminate_reason"] == "fused_stage_no_quality_signal"
    assert recall_delta["significant"] is False
