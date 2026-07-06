"""Pareto input uses end-to-end latency (stage_index=-1), not final-stage-only."""
from __future__ import annotations

from retrieval_observatory.dashboard.api import _extract_final_stage_metrics


def test_e2e_latency_preferred_over_final_stage():
    agg = {
        "a|0|ndcg|10|": {
            "pipeline_id": "hybrid__rerank",
            "stage_index": 1,
            "metric_name": "ndcg",
            "k": 10,
            "mean": 0.5,
        },
        "a|0|recall|10|": {
            "pipeline_id": "hybrid__rerank",
            "stage_index": 1,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.4,
        },
        "a|1|lat|50|": {
            "pipeline_id": "hybrid__rerank",
            "stage_index": 1,
            "metric_name": "latency_p50",
            "k": 0,
            "mean": 12.0,
        },
        "a|1|lat|95|": {
            "pipeline_id": "hybrid__rerank",
            "stage_index": 1,
            "metric_name": "latency_p95",
            "k": 0,
            "mean": 20.0,
        },
        "a|-1|lat|50|": {
            "pipeline_id": "hybrid__rerank",
            "stage_index": -1,
            "metric_name": "latency_p50",
            "k": 0,
            "mean": 85.0,
        },
        "a|-1|lat|95|": {
            "pipeline_id": "hybrid__rerank",
            "stage_index": -1,
            "metric_name": "latency_p95",
            "k": 0,
            "mean": 120.0,
        },
    }
    final = _extract_final_stage_metrics(agg)
    row = final["hybrid__rerank"]
    assert row["latency_p50"] == 85.0
    assert row["latency_p95"] == 120.0
    assert row["ndcg10"] == 0.5
