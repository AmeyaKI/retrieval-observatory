"""Metric orientation and thresholds are decided on the parsed metric name, never the key."""
from __future__ import annotations

import pytest

from retrieval_observatory.metrics.comparison import (
    ComparisonValidity,
    _effect_threshold,
    compare_paired_metrics,
    lower_is_better,
)
from retrieval_observatory.sdk.report import _headline_metrics


VALID = ComparisonValidity(outcome="valid", decision_allowed=True, differences=[], required_axes=[])


def _rows(pipeline, values, metric_name="recall", k=10):
    return [
        {"pipeline_id": pipeline, "stage_index": 0, "metric_name": metric_name, "k": k, "value": v, "query_id": f"q{i}", "branch_id": None}
        for i, v in enumerate(values)
    ]


@pytest.mark.parametrize("pipeline", ["bm25", "cost_aware_bm25", "low_latency_bm25", "profile_v2"])
def test_pipeline_name_does_not_flip_recall_orientation(pipeline):
    key = f"{pipeline}|stage0|recall@10"
    result = compare_paired_metrics(_rows(pipeline, [0.2] * 40), _rows(pipeline, [0.6] * 40), [key], VALID)[key]

    assert result.effect == pytest.approx(0.4)
    assert result.effect_threshold == 0.01
    assert result.decision == "candidate_better"
    assert _effect_threshold(key, 0.2) == 0.01


def test_latency_named_metric_on_plain_pipeline_is_lower_is_better():
    key = "bm25|stage0|latency_mean@0"
    rows = lambda values: _rows("bm25", values, metric_name="latency_ms", k=0)  # noqa: E731
    result = compare_paired_metrics(rows([100.0] * 40), rows([50.0] * 40), [key], VALID)[key]
    assert result.decision == "candidate_better"
    assert result.effect_threshold == 5.0


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("recall", False), ("ndcg", False), ("latency_p95", True), ("latency_mean", True),
        ("cost_usd", True), ("profile_compute_ms", True), ("failure", True), ("timeout", True), ("dropout_count", True),
    ],
)
def test_lower_is_better_by_metric_name_prefix(name, expected):
    assert lower_is_better(name) is expected


def test_headline_classifies_on_metric_name_not_pipeline_name():
    metrics = {
        "cost_aware_bm25|stage1|recall@10": {"mean": 0.9},
        "cost_aware_bm25|stage1|ndcg@10": {"mean": 0.8},
        "cost_aware_bm25|stage-1|latency_p50@0": {"mean": 12.0},
        "cost_aware_bm25|stage-1|latency_p95@0": {"mean": 40.0},
    }
    # ndcg leads the quality rows (sdk/report.py orders ndcg, recall, mrr, ...).
    assert list(_headline_metrics(metrics)) == [
        "cost_aware_bm25|stage1|ndcg@10",
        "cost_aware_bm25|stage1|recall@10",
        "cost_aware_bm25|stage-1|latency_p50@0",
        "cost_aware_bm25|stage-1|latency_p95@0",
    ]
