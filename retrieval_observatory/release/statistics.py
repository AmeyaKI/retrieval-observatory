from __future__ import annotations

from typing import Any, Literal, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from retrieval_observatory.metrics.comparison import parse_metric_key, scores_by_query
from retrieval_observatory.metrics.significance import paired_bootstrap_effect_ci
from retrieval_observatory.release.policy import MetricGuard, ReleasePolicy


GuardStatus = Literal["PASS", "HOLD", "BLOCK", "FAIL"]
Estimator = Literal["mean", "p50", "p95", "p99"]


class GuardResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    metric: str
    status: GuardStatus
    direction: Literal["higher_is_better", "lower_is_better"]
    max_regression: float
    estimator: Estimator
    baseline_estimate: float | None
    candidate_estimate: float | None
    effect: float | None
    ci_low: float | None
    ci_high: float | None
    paired_n: int
    min_paired_n: int
    seed: int
    resamples: int
    confidence_level: float
    adjusted_confidence_level: float
    interval_method: Literal["paired_percentile_bootstrap"] = "paired_percentile_bootstrap"
    sample_limitation: str | None = None
    affected_query_ids: list[str] = Field(default_factory=list)


def adjusted_confidence_level(policy: ReleasePolicy) -> float:
    guard_count = len(policy.metrics) * (1 + len(policy.slices))
    familywise_confidence = 1.0 - policy.statistics.familywise_alpha / guard_count
    return max(policy.statistics.confidence_level, familywise_confidence)


def evaluate_metric_guards(
    policy: ReleasePolicy,
    baseline_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
) -> list[GuardResult]:
    confidence = adjusted_confidence_level(policy)
    return [
        _evaluate_guard(guard, policy, baseline_rows, candidate_rows, confidence)
        for guard in policy.metrics
    ]


def _evaluate_guard(
    guard: MetricGuard,
    policy: ReleasePolicy,
    baseline_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
    confidence: float,
) -> GuardResult:
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(guard.metric)
    baseline_by_query = scores_by_query(
        list(baseline_rows), pipeline_id, stage_index, metric_name, k, branch_id=branch_id
    )
    candidate_by_query = scores_by_query(
        list(candidate_rows), pipeline_id, stage_index, metric_name, k, branch_id=branch_id
    )
    query_ids = sorted(set(baseline_by_query) & set(candidate_by_query))
    baseline = [baseline_by_query[query_id] for query_id in query_ids]
    candidate = [candidate_by_query[query_id] for query_id in query_ids]
    estimator = _estimator(metric_name)
    baseline_estimate = _estimate(baseline, estimator)
    candidate_estimate = _estimate(candidate, estimator)
    effect = (
        candidate_estimate - baseline_estimate
        if baseline_estimate is not None and candidate_estimate is not None
        else None
    )
    low, high = paired_bootstrap_effect_ci(
        baseline,
        candidate,
        estimator=estimator,
        n_resamples=policy.statistics.resamples,
        confidence_level=confidence,
        seed=policy.statistics.seed,
    )

    if not baseline_by_query or not candidate_by_query:
        status: GuardStatus = "BLOCK"
        limitation = "metric is unavailable in one or both runs"
    elif len(query_ids) < guard.min_paired_n:
        status = "HOLD"
        limitation = f"paired sample count {len(query_ids)} is below required {guard.min_paired_n}"
    else:
        status = _interval_status(guard, low, high)
        limitation = None

    return GuardResult(
        metric=guard.metric,
        status=status,
        direction=guard.direction,
        max_regression=guard.max_regression,
        estimator=estimator,
        baseline_estimate=baseline_estimate,
        candidate_estimate=candidate_estimate,
        effect=effect,
        ci_low=low,
        ci_high=high,
        paired_n=len(query_ids),
        min_paired_n=guard.min_paired_n,
        seed=policy.statistics.seed,
        resamples=policy.statistics.resamples,
        confidence_level=policy.statistics.confidence_level,
        adjusted_confidence_level=confidence,
        sample_limitation=limitation,
        affected_query_ids=[
            query_id
            for query_id, _ in sorted(
                (
                    (
                        query_id,
                        candidate_by_query[query_id] - baseline_by_query[query_id],
                    )
                    for query_id in query_ids
                ),
                key=lambda item: (
                    item[1] if guard.direction == "higher_is_better" else -item[1],
                    item[0],
                ),
            )[:20]
        ],
    )


def _interval_status(
    guard: MetricGuard,
    low: float | None,
    high: float | None,
) -> GuardStatus:
    if low is None or high is None:
        return "BLOCK"
    if guard.direction == "higher_is_better":
        boundary = -guard.max_regression
        if low >= boundary:
            return "PASS"
        if high < boundary:
            return "FAIL"
        return "HOLD"
    boundary = guard.max_regression
    if high <= boundary:
        return "PASS"
    if low > boundary:
        return "FAIL"
    return "HOLD"


def _estimator(metric_name: str) -> Estimator:
    for estimator in ("p50", "p95", "p99"):
        if metric_name.endswith(estimator):
            return estimator
    return "mean"


def _estimate(values: Sequence[float], estimator: Estimator) -> float | None:
    if not values:
        return None
    if estimator == "mean":
        return float(np.mean(values))
    return float(np.quantile(values, {"p50": 0.50, "p95": 0.95, "p99": 0.99}[estimator]))


__all__ = [
    "GuardResult",
    "adjusted_confidence_level",
    "evaluate_metric_guards",
    "paired_bootstrap_effect_ci",
]
