from retrieval_observatory.dashboard.api import (
    _compute_stage_contributions,
    _overview_warnings,
    _pipeline_topology,
)
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


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


def test_pipeline_topology_reports_fused_arms():
    metrics = {
        "fused__rerank|stage0|ndcg@10": {
            "pipeline_id": "fused__rerank",
            "stage_index": 0,
            "metric_name": "ndcg",
            "k": 10,
            "mean": 0.4,
            "branch_id": None,
        },
        "fused__rerank|stage0|latency_p50@0": {
            "pipeline_id": "fused__rerank",
            "stage_index": 0,
            "metric_name": "latency_p50",
            "k": 0,
            "mean": 12.0,
            "branch_id": None,
        },
        "fused__rerank|stage0|recall@10": {
            "pipeline_id": "fused__rerank",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.6,
            "branch_id": None,
        },
        "fused__rerank|stage0|recall@10|branch=bm25_stage": {
            "pipeline_id": "fused__rerank",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.3,
            "branch_id": "bm25_stage",
        },
    }
    results = [
        PipelineResult(
            query_id="q1",
            pipeline_id="fused__rerank",
            snapshots=[
                StageSnapshot(
                    stage_index=0,
                    stage_id="fused",
                    documents=[Document(id="d1", text="", score=1.0, rank=1)],
                    latency_ms=10.0,
                    candidate_count=5,
                    arms=[
                        StageSnapshot(
                            stage_index=0,
                            stage_id="bm25_stage",
                            documents=[Document(id="d1", text="", score=1.0, rank=1)],
                            latency_ms=4.0,
                            candidate_count=3,
                        )
                    ],
                )
            ],
            total_latency_ms=10.0,
            status="OK",
        )
    ]
    topo = _pipeline_topology(metrics, results)
    assert "fused__rerank" in topo
    assert topo["fused__rerank"][0]["kind"] == "fused"
    assert topo["fused__rerank"][0]["arms"][0]["arm_id"] == "bm25_stage"


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
