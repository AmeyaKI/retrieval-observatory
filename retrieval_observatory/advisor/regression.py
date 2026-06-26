from __future__ import annotations

from typing import List

from retrieval_observatory.advisor.types import RegressionFinding
from retrieval_observatory.metrics.comparison import paired_scores_by_query, parse_metric_key
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.significance import benjamini_hochberg, paired_bootstrap_test
from retrieval_observatory.store.base import BaseStore

_QUALITY_PREFIXES = ("ndcg", "recall", "mrr", "map")
_LATENCY_P95_SUFFIX = "latency_p95"
_LATENCY_REGRESSION_PCT = 0.20


def _is_quality_metric(metric_key: str) -> bool:
    _, _, metric_name, _, branch_id = parse_metric_key(metric_key)
    if branch_id:
        return False
    return any(metric_name.startswith(p) for p in _QUALITY_PREFIXES)


def _is_latency_p95(metric_key: str) -> bool:
    _, _, metric_name, _, branch_id = parse_metric_key(metric_key)
    if branch_id:
        return False
    return metric_name == _LATENCY_P95_SUFFIX


def _severity(delta: float, is_quality: bool) -> str:
    magnitude = abs(delta)
    if is_quality:
        if magnitude >= 0.1:
            return "high"
        if magnitude >= 0.05:
            return "medium"
        return "low"
    if magnitude >= 100:
        return "high"
    if magnitude >= 50:
        return "medium"
    return "low"


async def detect_regressions(
    baseline_run: str,
    candidate_run: str,
    store: BaseStore,
    *,
    engine: MetricsEngine | None = None,
    latency_regression_pct: float = _LATENCY_REGRESSION_PCT,
) -> List[RegressionFinding]:
    """Detect statistically significant quality drops or latency increases between two runs."""
    engine = engine or MetricsEngine()
    agg_base = await engine.aggregate(baseline_run, store)
    agg_cand = await engine.aggregate(candidate_run, store)
    metrics_base = await store.get_metrics(baseline_run)
    metrics_cand = await store.get_metrics(candidate_run)

    shared_keys = sorted(set(agg_base) & set(agg_cand))
    candidates: List[dict] = []

    for metric_key in shared_keys:
        if _is_quality_metric(metric_key):
            s1, s2, n_pairs = paired_scores_by_query(metrics_base, metrics_cand, metric_key)
            if n_pairs < 2:
                continue
            before = agg_base[metric_key]["mean"]
            after = agg_cand[metric_key]["mean"]
            if after >= before:
                continue
            p_value = paired_bootstrap_test(s1, s2)
            candidates.append(
                {
                    "metric": metric_key,
                    "before": before,
                    "after": after,
                    "delta": after - before,
                    "p_value": p_value,
                    "n_pairs": n_pairs,
                    "is_quality": True,
                }
            )
        elif _is_latency_p95(metric_key):
            before = agg_base[metric_key]["mean"]
            after = agg_cand[metric_key]["mean"]
            if before <= 0:
                continue
            rel_increase = (after - before) / before
            if rel_increase < latency_regression_pct:
                continue
            s1, s2, n_pairs = paired_scores_by_query(metrics_base, metrics_cand, metric_key)
            if n_pairs < 2:
                continue
            p_value = paired_bootstrap_test(s1, s2)
            candidates.append(
                {
                    "metric": metric_key,
                    "before": before,
                    "after": after,
                    "delta": after - before,
                    "p_value": p_value,
                    "n_pairs": n_pairs,
                    "is_quality": False,
                }
            )

    if not candidates:
        return []

    q_values = benjamini_hochberg([c["p_value"] for c in candidates])
    findings: List[RegressionFinding] = []
    for candidate, q_value in zip(candidates, q_values):
        if q_value >= 0.05:
            continue
        findings.append(
            RegressionFinding(
                metric=candidate["metric"],
                before=candidate["before"],
                after=candidate["after"],
                delta=candidate["delta"],
                q_value=q_value,
                severity=_severity(candidate["delta"], candidate["is_quality"]),
                n_pairs=candidate["n_pairs"],
            )
        )
    findings.sort(key=lambda f: f.q_value)
    return findings
