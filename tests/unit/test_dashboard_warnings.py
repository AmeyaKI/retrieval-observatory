from retrieval_observatory.dashboard.api import _overview_warnings


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
