"""Headline metrics: one row per metric name at the largest k, ordered by decision value,
capped per pipeline and overall."""
from __future__ import annotations

from retrieval_observatory.sdk.report import _headline_metrics


def _row(key: str) -> dict:
    return {"mean": 1.0, "metric_name": key.split("|")[2].split("@")[0]}


def test_review_key_set_collapses_recall_to_the_largest_k() -> None:
    keys = [
        "retrieve|stage0|latency_p50@0", "retrieve|stage0|latency_p95@0",
        "retrieve|stage0|recall@1", "retrieve|stage0|recall@10", "retrieve|stage0|recall@5",
    ]
    assert list(_headline_metrics({key: _row(key) for key in keys})) == [
        "retrieve|stage0|recall@10", "retrieve|stage0|latency_p50@0", "retrieve|stage0|latency_p95@0",
    ]


def test_final_stage_per_pipeline_ordered_and_capped() -> None:
    keys = []
    for pipeline, final in (("bm25", 0), ("hybrid", 1), ("dense", 0)):
        for stage in range(final + 1):
            for name in ("precision", "map", "mrr", "recall", "ndcg"):
                for k in (1, 5, 10):
                    keys.append(f"{pipeline}|stage{stage}|{name}@{k}")
        keys.append(f"{pipeline}|stage-1|latency_p50@0")
    headline = list(_headline_metrics({key: _row(key) for key in keys}))
    quality = [key for key in headline if "latency" not in key]
    assert quality == [
        "bm25|stage0|ndcg@10", "bm25|stage0|recall@10", "bm25|stage0|mrr@10",
        "dense|stage0|ndcg@10", "dense|stage0|recall@10", "dense|stage0|mrr@10",
    ]
    assert headline[len(quality):] == ["bm25|stage-1|latency_p50@0", "dense|stage-1|latency_p50@0"]
    assert "hybrid|stage0|ndcg@10" not in headline  # hybrid's terminal stage is 1, and the cap of 6 rows is already reached
