from retrieval_observatory.dashboard.api import _overview_warnings, _pipeline_topology
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
