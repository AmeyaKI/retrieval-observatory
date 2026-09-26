from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from retrieval_observatory.metrics.comparison import (
    FAILURE_INDICATOR_METRICS,
    PairCoverage,
    pair_coverage,
    parse_metric_key,
    scores_by_query,
)
from retrieval_observatory.metrics.significance import paired_bootstrap_effect_ci
from retrieval_observatory.release.policy import MetricGuard, ReleasePolicy
from retrieval_observatory.release.resolution import (
    CheckStatus,
    ResolvedCheck,
    ResolvedPolicy,
    RunEvidence,
    minimum_resamples,
)


GuardStatus = Literal["PASS", "HOLD", "BLOCK", "FAIL"]
Estimator = Literal["mean", "p50", "p95", "p99"]

# Frozen operational codes.
FAILURE_RATE_EXCEEDED = "failure_rate_exceeded"
ATTEMPT_ACCOUNTING_UNKNOWN = "attempt_accounting_unknown"


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
    attempted_n: int = 0
    pair_coverage: float | None = None
    min_pair_coverage: float = 0.95
    seed: int
    resamples: int
    confidence_level: float
    adjusted_confidence_level: float
    interval_method: Literal["paired_percentile_bootstrap"] = "paired_percentile_bootstrap"
    sample_limitation: str | None = None
    affected_query_ids: list[str] = Field(default_factory=list)


class CheckResult(GuardResult):
    """One resolved v3 check. ``metric`` is the display key (the candidate's resolved key, with the
    latency estimator named); ``metric_key_by_run`` records what each run was actually read at."""

    check_id: str
    target: str
    metric_key_by_run: dict[str, str | None]
    family_size: int
    resolution_status: CheckStatus


class RunExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str
    attempted_n: int | None
    failed_n: int
    failure_rate: float | None
    attempted_source: Literal["manifest", "metric_rows", "unknown"]


class OperationalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["PASS", "BLOCK", "FAIL"]
    code: str | None
    max_failure_rate: float
    baseline: RunExecution
    candidate: RunExecution
    detail: str


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
    coverage = pair_coverage(baseline_by_query, candidate_by_query, baseline_rows, candidate_rows, pipeline_id)
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
    elif coverage.below(policy.statistics.min_pair_coverage):
        # Failed queries have no rows to pair; the interval above describes only the
        # survivors, so it cannot clear a candidate that dropped the hard queries.
        status = "HOLD"
        limitation = coverage.reason()
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
        attempted_n=coverage.attempted_n,
        pair_coverage=coverage.coverage,
        min_pair_coverage=policy.statistics.min_pair_coverage,
        seed=policy.statistics.seed,
        resamples=policy.statistics.resamples,
        confidence_level=policy.statistics.confidence_level,
        adjusted_confidence_level=confidence,
        sample_limitation=limitation,
        affected_query_ids=_affected_query_ids(guard.direction, baseline_by_query, candidate_by_query, query_ids),
    )


# --------------------------------------------------------------------------- resolved (v3) checks


def resolved_family_size(resolved: ResolvedPolicy) -> int:
    """Every check plus, per slice, its resolved metric ids (an unresolved check still counts)."""
    return len(resolved.checks) + sum(len(item.metric_ids) for item in resolved.slices)


def resolved_adjusted_confidence(resolved: ResolvedPolicy) -> float:
    statistics = resolved.statistics
    familywise = 1.0 - statistics["familywise_alpha"] / resolved_family_size(resolved)
    return max(statistics["confidence_level"], familywise)


def query_universe(baseline: RunEvidence, candidate: RunEvidence, expected: set[str] | None) -> set[str]:
    """The queries a comparison must account for: the caller's attempted set, else every query with a row."""
    if expected is not None:
        return set(expected)
    return {row["query_id"] for run in (baseline, candidate) for row in run.metric_rows}


def evaluate_resolved_checks(
    resolved: ResolvedPolicy,
    baseline: RunEvidence,
    candidate: RunEvidence,
    *,
    expected_query_ids: set[str] | None = None,
) -> list[CheckResult]:
    universe = query_universe(baseline, candidate, expected_query_ids)
    return [evaluate_resolved_check(check, resolved, baseline, candidate, universe) for check in resolved.checks]


def evaluate_resolved_check(
    check: ResolvedCheck,
    resolved: ResolvedPolicy,
    baseline: RunEvidence,
    candidate: RunEvidence,
    query_ids: set[str],
) -> CheckResult:
    """Evaluate one check at each run's own resolved key over the ``query_ids`` universe.

    ``attempted_n`` is the universe (plus any query with a value); a query missing a value in
    either run is counted, never dropped, so pair loss shows up as coverage.
    """
    statistics = resolved.statistics
    family = resolved_family_size(resolved)
    adjusted = resolved_adjusted_confidence(resolved)
    resamples, seed = int(statistics["resamples"]), int(statistics["seed"])
    baseline_key = check.metric_key_by_run.get(baseline.run_id)
    candidate_key = check.metric_key_by_run.get(candidate.run_id)
    baseline_by_query = _values(baseline.metric_rows, baseline_key)
    candidate_by_query = _values(candidate.metric_rows, candidate_key)
    paired_ids = sorted(set(baseline_by_query) & set(candidate_by_query))
    attempted = set(query_ids) | set(baseline_by_query) | set(candidate_by_query)
    coverage = PairCoverage(
        paired_n=len(paired_ids),
        attempted_n=len(attempted),
        coverage=len(paired_ids) / len(attempted) if attempted else None,
        missing_baseline=len(attempted - set(baseline_by_query)),
        missing_candidate=len(attempted - set(candidate_by_query)),
    )
    baseline_values = [baseline_by_query[query_id] for query_id in paired_ids]
    candidate_values = [candidate_by_query[query_id] for query_id in paired_ids]
    estimator: Estimator = check.estimator  # type: ignore[assignment]
    baseline_estimate = _estimate(baseline_values, estimator)
    candidate_estimate = _estimate(candidate_values, estimator)
    effect = (
        candidate_estimate - baseline_estimate
        if baseline_estimate is not None and candidate_estimate is not None
        else None
    )
    floor = _resolution_floor(resamples, adjusted, family)
    low = high = None
    if floor is None and baseline_values:
        low, high = paired_bootstrap_effect_ci(
            baseline_values,
            candidate_values,
            estimator=estimator,
            n_resamples=resamples,
            confidence_level=adjusted,
            seed=seed,
        )

    if check.status != "resolved" or baseline_key is None or candidate_key is None:
        status: GuardStatus = "BLOCK"
        limitation: str | None = check.detail or f"check {check.id} is {check.status}"
    elif floor is not None:
        status, limitation = "BLOCK", floor
    elif not baseline_by_query or not candidate_by_query:
        status, limitation = "BLOCK", "metric is unavailable in one or both runs"
    elif len(paired_ids) < check.min_paired_n:
        status = "HOLD"
        limitation = f"paired sample count {len(paired_ids)} is below required {check.min_paired_n}"
    elif coverage.below(float(statistics["min_pair_coverage"])):
        status, limitation = "HOLD", coverage.reason()
    else:
        status, limitation = _interval_status(check, low, high), None

    return CheckResult(
        check_id=check.id,
        target=check.target,
        metric_key_by_run=dict(check.metric_key_by_run),
        family_size=family,
        resolution_status=check.status,
        metric=_display_key(check, candidate_key or baseline_key),
        status=status,
        direction=check.direction,  # type: ignore[arg-type]
        max_regression=check.max_regression,
        estimator=estimator,
        baseline_estimate=baseline_estimate,
        candidate_estimate=candidate_estimate,
        effect=effect,
        ci_low=low,
        ci_high=high,
        paired_n=len(paired_ids),
        min_paired_n=check.min_paired_n,
        attempted_n=coverage.attempted_n,
        pair_coverage=coverage.coverage,
        min_pair_coverage=float(statistics["min_pair_coverage"]),
        seed=seed,
        resamples=resamples,
        confidence_level=float(statistics["confidence_level"]),
        adjusted_confidence_level=adjusted,
        sample_limitation=limitation,
        affected_query_ids=_affected_query_ids(check.direction, baseline_by_query, candidate_by_query, paired_ids),
    )


# --------------------------------------------------------------------------- execution accounting


def evaluate_execution(resolved: ResolvedPolicy, baseline: RunEvidence, candidate: RunEvidence) -> OperationalResult:
    """Failure-rate breach is FAIL; missing attempt accounting is BLOCK. Baseline failures are reported only."""
    cap = float(resolved.execution.get("max_failure_rate", 0.0))
    runs = {run.run_id: _run_execution(run) for run in (baseline, candidate)}
    unknown = [run_id for run_id, item in runs.items() if item.failure_rate is None]
    if unknown:
        status, code = "BLOCK", ATTEMPT_ACCOUNTING_UNKNOWN
        detail = (
            f"attempted query count is unknown for run {', '.join(unknown)}; "
            "record manifest counts.attempted or per-query failure indicator rows"
        )
    else:
        item = runs[candidate.run_id]
        rate = item.failure_rate or 0.0
        detail = f"candidate {candidate.run_id} failed {item.failed_n} of {item.attempted_n} attempted queries ({rate:.1%})"
        if rate > cap:
            status, code = "FAIL", FAILURE_RATE_EXCEEDED
            detail += f"; the policy allows at most {cap:.1%}"
        else:
            status, code = "PASS", None
            detail += f"; within the {cap:.1%} budget"
    return OperationalResult(
        status=status,
        code=code,
        max_failure_rate=cap,
        baseline=runs[baseline.run_id],
        candidate=runs[candidate.run_id],
        detail=detail,
    )


def _run_execution(run: RunEvidence) -> RunExecution:
    indicators = [row for row in run.metric_rows if row.get("metric_name") in FAILURE_INDICATOR_METRICS]
    failed = {row["query_id"] for row in indicators if float(row["value"]) > 0.0}
    counts = run.manifest.get("counts") if isinstance(run.manifest, Mapping) else None
    attempted = counts.get("attempted") if isinstance(counts, Mapping) else None
    completed = counts.get("completed") if isinstance(counts, Mapping) else None
    failed_n = len(failed)
    if _is_count(attempted) and attempted > 0:
        source = "manifest"
        if _is_count(completed):
            # Indicator rows exist only for judged queries (the metrics engine skips queries
            # without positive judgments), so a failed unjudged query is invisible to them while
            # the manifest still counts it as attempted. The manifest's attempted-minus-completed
            # covers every query; take the larger of the two accountings.
            failed_n = max(failed_n, int(attempted) - int(completed), 0)
    else:
        attempted = len({row["query_id"] for row in run.metric_rows}) or None
        source = "metric_rows" if attempted else "unknown"
    return RunExecution(
        run_id=run.run_id,
        attempted_n=int(attempted) if attempted else None,
        failed_n=failed_n,
        failure_rate=failed_n / int(attempted) if attempted else None,
        attempted_source=source,
    )


# --------------------------------------------------------------------------- helpers


def _interval_status(
    guard: MetricGuard | ResolvedCheck,
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


def _resolution_floor(resamples: int, adjusted: float, family: int) -> str | None:
    """The policy validator's floor, re-checked over the family the resolved slices produced."""
    if resamples * (1.0 - adjusted) / 2 < 20:
        return (
            f"resamples {resamples} cannot resolve the adjusted {adjusted:.6g} confidence interval over "
            f"{family} checks; at least {minimum_resamples(adjusted)} resamples are required"
        )
    return None


def _values(rows: Sequence[Mapping[str, Any]], key: str | None) -> dict[str, float]:
    if key is None:
        return {}
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(key)
    return scores_by_query(list(rows), pipeline_id, stage_index, metric_name, k, branch_id=branch_id)


def _display_key(check: ResolvedCheck, key: str | None) -> str:
    if key is None:
        return f"{check.target}:{check.metric}"
    if check.metric == "latency_ms" and check.estimator != "mean":
        # The estimator-named render key of metrics/comparison (latency_p95 pairs the same
        # per-query latency_ms samples); the estimator field is authoritative.
        return key.replace("|latency_ms@", f"|latency_{check.estimator}@", 1)
    return key


def _affected_query_ids(
    direction: str,
    baseline_by_query: Mapping[str, float],
    candidate_by_query: Mapping[str, float],
    query_ids: Sequence[str],
) -> list[str]:
    ranked = sorted(
        ((query_id, candidate_by_query[query_id] - baseline_by_query[query_id]) for query_id in query_ids),
        key=lambda item: (item[1] if direction == "higher_is_better" else -item[1], item[0]),
    )
    return [query_id for query_id, _ in ranked[:20]]


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
    "ATTEMPT_ACCOUNTING_UNKNOWN",
    "FAILURE_RATE_EXCEEDED",
    "CheckResult",
    "GuardResult",
    "OperationalResult",
    "RunExecution",
    "adjusted_confidence_level",
    "evaluate_execution",
    "evaluate_metric_guards",
    "evaluate_resolved_check",
    "evaluate_resolved_checks",
    "paired_bootstrap_effect_ci",
    "query_universe",
    "resolved_adjusted_confidence",
    "resolved_family_size",
]
