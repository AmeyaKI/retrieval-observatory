from __future__ import annotations

from retrieval_observatory.tracing.monitor.cluster import compute_clusters


def test_semantic_clustering_groups_similar_queries() -> None:
    traces = [
        {"query_text": "annual revenue growth report", "total_latency_ms": 10.0, "predicted_difficulty": "easy"},
        {"query_text": "quarterly revenue growth summary", "total_latency_ms": 12.0, "predicted_difficulty": "easy"},
        {"query_text": "revenue growth annual filing", "total_latency_ms": 11.0, "predicted_difficulty": "medium"},
        {"query_text": "how to bake sourdough bread", "total_latency_ms": 50.0, "predicted_difficulty": "hard"},
        {"query_text": "sourdough bread baking tips", "total_latency_ms": 55.0, "predicted_difficulty": "hard"},
        {"query_text": "best sourdough starter recipe", "total_latency_ms": 48.0, "predicted_difficulty": "hard"},
    ]
    clusters = compute_clusters(traces)
    assert clusters
    assert sum(c["size"] for c in clusters) == len(traces)
