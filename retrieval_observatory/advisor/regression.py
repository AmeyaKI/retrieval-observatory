from __future__ import annotations

from typing import List

from retrieval_observatory.advisor.types import RegressionFinding
from retrieval_observatory.metrics.comparison import compare_paired_metrics, comparison_validity, parse_metric_key
from retrieval_observatory.metrics.engine import MetricsEngine
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
    manifests = [
        await store.get_run_manifest(baseline_run),
        await store.get_run_manifest(candidate_run),
    ]
    validity = comparison_validity(manifests)
    if not validity.decision_allowed:
        return []
    statistical_results = compare_paired_metrics(
        metrics_base,
        metrics_cand,
        shared_keys,
        validity,
    )
    candidates: List[dict] = []

    for metric_key in shared_keys:
        if _is_quality_metric(metric_key):
            before = agg_base[metric_key]["mean"]
            after = agg_cand[metric_key]["mean"]
            result = statistical_results[metric_key]
            if result.decision != "candidate_worse":
                continue
            candidates.append(
                {
                    "metric": metric_key,
                    "before": before,
                    "after": after,
                    "delta": after - before,
                    "p_value": result.p_value,
                    "q_value": result.q_value,
                    "effect_threshold": result.effect_threshold,
                    "n_pairs": result.paired_n,
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
            result = statistical_results[metric_key]
            if result.decision != "candidate_worse":
                continue
            candidates.append(
                {
                    "metric": metric_key,
                    "before": before,
                    "after": after,
                    "delta": after - before,
                    "p_value": result.p_value,
                    "q_value": result.q_value,
                    "effect_threshold": result.effect_threshold,
                    "n_pairs": result.paired_n,
                    "is_quality": False,
                }
            )

    if not candidates:
        return []

    findings: List[RegressionFinding] = []
    for candidate in candidates:
        q_value = candidate["q_value"]
        findings.append(
            RegressionFinding(
                metric=candidate["metric"],
                before=candidate["before"],
                after=candidate["after"],
                delta=candidate["delta"],
                q_value=q_value,
                severity=_severity(candidate["delta"], candidate["is_quality"]),
                n_pairs=candidate["n_pairs"],
                p_value=candidate["p_value"],
                effect_threshold=candidate["effect_threshold"],
            )
        )
    findings.sort(key=lambda f: f.q_value)
    return findings
