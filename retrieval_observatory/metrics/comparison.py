from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from retrieval_observatory.metrics.significance import benjamini_hochberg, paired_bootstrap_test


MetricKey = Tuple[str, int, str, int, Optional[str]]


@dataclass
class ComparisonDifference:
    axis: str
    severity: Literal["high", "medium", "low"]
    status: Literal["invalid", "warning", "unknown"]
    detail: str
    values: List[Any]


@dataclass
class ComparisonValidity:
    outcome: Literal["valid", "warning", "invalid"]
    decision_allowed: bool
    differences: List[ComparisonDifference]
    required_axes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "comparable": self.decision_allowed,
            "decision_allowed": self.decision_allowed,
            "differences": [asdict(difference) for difference in self.differences],
            "required_axes": list(self.required_axes),
        }


@dataclass
class StatisticalComparison:
    metric: str
    baseline_mean: Optional[float]
    candidate_mean: Optional[float]
    effect: Optional[float]
    effect_threshold: Optional[float]
    p_value: Optional[float]
    q_value: Optional[float]
    paired_n: int
    low_power: bool
    significant: Optional[bool]
    decision: Literal["candidate_better", "candidate_worse", "no_decision"]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REQUIRED_COMPARISON_AXES = ("query_hash", "corpus_hash", "qrel_hash", "labeling")


def comparison_validity(manifests: List[Dict[str, Any] | None]) -> ComparisonValidity:
    """Validate whether two or more manifests support a decision-bearing comparison."""
    differences: List[ComparisonDifference] = []

    def values_for(axis: str) -> List[Any]:
        if axis == "labeling":
            return [
                (
                    (manifest or {}).get("labeling", {}).get("method"),
                    (manifest or {}).get("labeling", {}).get("judge"),
                    (manifest or {}).get("labeling", {}).get("model"),
                    (manifest or {}).get("labeling", {}).get("version"),
                )
                if manifest else None
                for manifest in manifests
            ]
        return [((manifest or {}).get("dataset", {}) or {}).get(axis) for manifest in manifests]

    for axis in REQUIRED_COMPARISON_AXES:
        values = values_for(axis)
        missing = any(value is None or (axis == "labeling" and value[0] is None) for value in values)
        if missing:
            differences.append(ComparisonDifference(
                axis=axis,
                severity="high",
                status="unknown",
                detail=f"Required comparison metadata '{axis}' is missing; equality cannot be established.",
                values=values,
            ))
        elif len({repr(value) for value in values}) > 1:
            differences.append(ComparisonDifference(
                axis=axis,
                severity="high",
                status="invalid",
                detail=f"Runs differ on required comparison axis '{axis}'.",
                values=values,
            ))

    optional_axes = {
        "seed": lambda manifest: (manifest or {}).get("execution", {}).get("seed", (manifest or {}).get("seed")),
        "cache": lambda manifest: (manifest or {}).get("execution", {}).get("cache_results", (manifest or {}).get("cache_results")),
        "timeout": lambda manifest: (manifest or {}).get("execution", {}).get("timeout_ms"),
        "git_commit": lambda manifest: (manifest or {}).get("git_commit"),
        "git_dirty": lambda manifest: (manifest or {}).get("git_dirty"),
        "models": lambda manifest: (manifest or {}).get("models"),
        "package_versions": lambda manifest: (manifest or {}).get("packages"),
    }
    for axis, getter in optional_axes.items():
        values = [getter(manifest) for manifest in manifests]
        known = [value for value in values if value is not None and value != {} and value != []]
        if len(known) != len(values):
            differences.append(ComparisonDifference(
                axis=axis,
                severity="low",
                status="unknown",
                detail=f"Optional comparison metadata '{axis}' is missing for at least one run.",
                values=values,
            ))
        elif len({repr(value) for value in known}) > 1:
            differences.append(ComparisonDifference(
                axis=axis,
                severity="medium" if axis in {"cache", "timeout", "models"} else "low",
                status="warning",
                detail=f"Runs differ on optional comparison axis '{axis}'.",
                values=values,
            ))

    invalid = any(
        difference.status in {"invalid", "unknown"} and difference.axis in REQUIRED_COMPARISON_AXES
        for difference in differences
    )
    outcome: Literal["valid", "warning", "invalid"] = "invalid" if invalid else "warning" if differences else "valid"
    return ComparisonValidity(
        outcome=outcome,
        decision_allowed=not invalid,
        differences=differences,
        required_axes=list(REQUIRED_COMPARISON_AXES),
    )


def compare_paired_metrics(
    metrics_baseline: List[Dict],
    metrics_candidate: List[Dict],
    metric_keys: List[str],
    validity: ComparisonValidity,
    *,
    min_power_n: int = 20,
    alpha: float = 0.05,
) -> Dict[str, StatisticalComparison]:
    """Compute one BH-corrected paired result set with explicit baseline orientation."""
    results: Dict[str, StatisticalComparison] = {}
    tested_keys: List[str] = []
    raw_p_values: List[float] = []
    for metric_key in metric_keys:
        baseline, candidate, paired_n = paired_scores_by_query(metrics_baseline, metrics_candidate, metric_key)
        baseline_mean = sum(baseline) / paired_n if paired_n else None
        candidate_mean = sum(candidate) / paired_n if paired_n else None
        effect = candidate_mean - baseline_mean if baseline_mean is not None and candidate_mean is not None else None
        threshold = _effect_threshold(metric_key, baseline_mean)
        p_value = paired_bootstrap_test(baseline, candidate) if validity.decision_allowed and paired_n >= 2 else None
        result = StatisticalComparison(
            metric=metric_key,
            baseline_mean=baseline_mean,
            candidate_mean=candidate_mean,
            effect=effect,
            effect_threshold=threshold,
            p_value=p_value,
            q_value=None,
            paired_n=paired_n,
            low_power=paired_n < min_power_n,
            significant=None,
            decision="no_decision",
            reason=(
                "comparison validity failed"
                if not validity.decision_allowed
                else "insufficient paired samples"
                if paired_n < min_power_n
                else "awaiting multiple-testing correction"
            ),
        )
        results[metric_key] = result
        if p_value is not None:
            tested_keys.append(metric_key)
            raw_p_values.append(p_value)

    for metric_key, q_value in zip(tested_keys, benjamini_hochberg(raw_p_values)):
        result = results[metric_key]
        result.q_value = q_value
        result.significant = q_value < alpha
        if result.low_power:
            result.reason = "insufficient paired samples"
        elif not result.significant:
            result.reason = "effect is not significant after BH correction"
        elif result.effect is None or result.effect_threshold is None or abs(result.effect) < result.effect_threshold:
            result.reason = "effect is below the declared practical threshold"
        else:
            lower_is_better = any(token in metric_key for token in ("latency", "cost", "profile"))
            favorable = result.effect < 0 if lower_is_better else result.effect > 0
            result.decision = "candidate_better" if favorable else "candidate_worse"
            result.reason = "significant paired effect exceeds the practical threshold"
    return results


def _effect_threshold(metric_key: str, baseline_mean: Optional[float]) -> Optional[float]:
    if baseline_mean is None:
        return None
    # Profile counters are wall-clock adjacent noise at sub-ms scale; use the same
    # relative floor as latency so they do not become flaky decision-bearing gates.
    if any(token in metric_key for token in ("latency", "profile")):
        return max(1.0, abs(baseline_mean) * 0.05)
    if "cost" in metric_key:
        return max(0.001, abs(baseline_mean) * 0.05)
    return 0.01


def pipeline_pairs(pipeline_ids: List[str]) -> List[Tuple[str, str]]:
    """Return (before, after) pairs for adjacent pipeline stages.

    A pipeline ID with __ separators (e.g. "bm25__rerank") is treated as a
    multi-stage pipeline. If its prefix ("bm25") also exists in pipeline_ids,
    the two form a pair. This is used to measure what each added stage contributed.

    Examples:
        ["bm25", "bm25__rerank"] -> [("bm25", "bm25__rerank")]
        ["bm25", "bm25__rerank", "bm25__rerank__cohere"] ->
            [("bm25", "bm25__rerank"), ("bm25__rerank", "bm25__rerank__cohere")]
    """
    id_set = set(pipeline_ids)
    pairs: List[Tuple[str, str]] = []
    for pid in pipeline_ids:
        parts = pid.split("__")
        if len(parts) > 1:
            prefix = "__".join(parts[:-1])
            if prefix in id_set:
                pairs.append((prefix, pid))
    return pairs


def paired_scores_by_query(metrics_a: List[Dict], metrics_b: List[Dict], metric_key: str) -> tuple[list[float], list[float], int]:
    """Return score arrays joined by query_id for a rendered metric key.

    metric_key format matches aggregate keys: pipeline|stageN|metric@k.
    """
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(metric_key)
    a = scores_by_query(metrics_a, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
    b = scores_by_query(metrics_b, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
    query_ids = sorted(set(a) & set(b))
    return [a[qid] for qid in query_ids], [b[qid] for qid in query_ids], len(query_ids)


def parse_metric_key(key: str) -> MetricKey:
    parts = key.split("|")
    if len(parts) < 3:
        raise ValueError(f"Invalid metric key: {key}")
    pipeline_id, stage_part, metric_part = parts[:3]
    stage_index = int(stage_part.removeprefix("stage"))
    metric_name, k_text = metric_part.rsplit("@", 1)
    branch_id = None
    if len(parts) >= 4 and parts[3].startswith("branch="):
        branch_id = parts[3].split("=", 1)[1]
    return pipeline_id, stage_index, metric_name, int(k_text), branch_id


QUALITY_METRIC_ORDER = ("recall", "ndcg", "precision", "mrr", "map")


def rank_metric_keys(keys: Iterable[str], *, policy_metrics: Iterable[str] = ()) -> List[str]:
    """Order metric keys by how much they bear on a release decision, most first.

    Sorting metric keys as plain strings puts ``stage-1`` ahead of ``stage0``…``stage8``,
    because '-' precedes digits — so a comparison table opens on run-level operational rows
    (dropout_count, failure_rate, timeout_rate, latency) while the terminal-stage quality
    that actually answers "did this get worse?" sorts last, behind a hundred other rows.

    Tiers: policy-guarded metrics, then terminal-stage quality, then the rest of the quality
    funnel (spine before per-branch rows, which only cover the queries routed down that
    branch), then operational.
    """
    guarded = set(policy_metrics)
    parsed: Dict[str, MetricKey] = {}
    for key in keys:
        try:
            parsed[key] = parse_metric_key(key)
        except (TypeError, ValueError, IndexError):
            continue
    unparsed = [key for key in keys if key not in parsed]

    quality_stages = [
        stage for _p, stage, name, _k, branch in parsed.values()
        if name in QUALITY_METRIC_ORDER and branch is None
    ]
    final_stage = max(quality_stages, default=None)

    def rank(key: str) -> tuple:
        _pipeline, stage_index, metric_name, k, branch_id = parsed[key]
        is_quality = metric_name in QUALITY_METRIC_ORDER
        quality_rank = QUALITY_METRIC_ORDER.index(metric_name) if is_quality else len(QUALITY_METRIC_ORDER)
        if key in guarded:
            tier = 0
        elif is_quality and branch_id is None and stage_index == final_stage:
            tier = 1
        elif is_quality:
            tier = 2
        else:
            tier = 3
        # Within the funnel, later stages first: they are closer to what the caller ships.
        return (tier, -stage_index if tier == 2 else 0, branch_id is not None, quality_rank, k, key)

    return sorted(parsed, key=rank) + sorted(unparsed)


def scores_by_query(
    metrics: List[Dict],
    pipeline_id: str,
    stage_index: int,
    metric_name: str,
    k: int,
    branch_id: Optional[str] = None,
) -> Dict[str, float]:
    # Percentiles are aggregate render keys over the persisted per-query latency_ms
    # samples. Pair the underlying samples by query for significance/effect tests.
    stored_metric_name = "latency_ms" if metric_name in {"latency_p50", "latency_p95", "latency_p99"} else metric_name
    return {
        row["query_id"]: row["value"]
        for row in metrics
        if row["pipeline_id"] == pipeline_id
        and row["stage_index"] == stage_index
        and row["metric_name"] == stored_metric_name
        and row["k"] == k
        and row.get("branch_id") == branch_id
    }


# Backward-compatible internal alias used by the existing dashboard comparison path.
_scores_for = scores_by_query
