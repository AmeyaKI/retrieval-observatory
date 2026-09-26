"""Selector resolution: bind a release policy's semantic selectors to the metric keys two runs record.

A v3 policy names *what* to guard (``final_retrieval``, ``query``, ``operator:<id>``); this module
resolves each check to the canonical ``pipeline|stageN|metric@k[|branch=..]`` key of every run and
records why a check could not be bound. Nothing here evaluates statistics: the resolved structure
is what ``release.statistics``, ``release.slices`` and ``release.decision`` consume directly, each run
read at its own key.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import ValidationError

from retrieval_observatory.metrics.comparison import parse_metric_key
from retrieval_observatory.release.policy import (
    CUTOFF_METRICS,
    FINAL_RETRIEVAL,
    OPERATOR_SELECTOR_PREFIX,
    EvidenceRequirements,
    InterventionDeclaration,
    MetricGuard,
    PromotionEvidenceRequirements,
    ReleasePolicy,
    ReleasePolicyV3,
    SliceGuard,
    StatisticsPolicy,
)


CheckStatus = Literal["resolved", "absent", "ambiguous", "unsupported"]
AGGREGATE_SCOPE = "aggregate_or_slice_evaluation"

# Frozen finding codes.
METRIC_SELECTOR_UNRESOLVED = "metric_selector_unresolved"
POLICY_SELECTOR_AMBIGUOUS = "policy_selector_ambiguous"
POLICY_CONVERSION_INVALID = "policy_conversion_invalid"

# Per-query keys the metrics engine writes for query-level checks (metrics/engine.py).
_QUERY_LEVEL_STORED = {"latency_ms": "latency_ms", "failure_rate": "failure"}
_STATISTICS_FIELDS = ("confidence_level", "familywise_alpha", "resamples", "seed", "min_pair_coverage")
# Never evaluated: assess_evidence needs a v2 policy shape; decide_release_v3 reports v3 checks itself.
_PLACEHOLDER_GUARD = "unresolved|stage0|unresolved@0"
_ID_SANITIZE = re.compile(r"[^a-z0-9._-]+")
_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


# --------------------------------------------------------------------------- family size


def family_size(policy: ReleasePolicyV3) -> int:
    """Predeclared checks: every metric check plus, per slice, its metric_ids (all when empty)."""
    return len(policy.metrics) + sum(len(item.metric_ids) or len(policy.metrics) for item in policy.slices)


def adjusted_confidence(policy: ReleasePolicyV3) -> float:
    """Bonferroni rule of statistics.adjusted_confidence_level over the v3 family size."""
    familywise = 1.0 - policy.statistics.familywise_alpha / family_size(policy)
    return max(policy.statistics.confidence_level, familywise)


def minimum_resamples(adjusted: float) -> int:
    return math.ceil(40 / (1.0 - adjusted) - 1e-9)


def validate_bootstrap_resolution(policy: ReleasePolicyV3) -> None:
    """Numerical-resolution floor ``resamples * (1 - adjusted) / 2 >= 20``; not inferential proof."""
    adjusted = adjusted_confidence(policy)
    resamples = policy.statistics.resamples
    if resamples * (1.0 - adjusted) / 2 < 20:
        raise ValueError(
            f"resamples {resamples} cannot resolve the adjusted {adjusted:.6g} confidence interval over "
            f"{family_size(policy)} checks; at least {minimum_resamples(adjusted)} resamples are required"
        )


# --------------------------------------------------------------------------- run evidence


@dataclass(frozen=True)
class RunEvidence:
    run_id: str
    manifest: Mapping[str, Any]
    metric_rows: Sequence[Mapping[str, Any]]
    #: op_id -> (stage_index, branch_id) as the metrics engine assigns them; None when traces
    #: were not loaded.
    operator_depths: Mapping[str, tuple[int, str | None]] | None = None
    #: op_id -> stable operator_id (``rerank@dense`` -> ``rerank``); None when traces were not loaded.
    operator_ids: Mapping[str, str] | None = None


def operator_depths_from_traces(traces: Iterable[Any]) -> dict[str, tuple[int, str | None]]:
    """Stage index and branch id of every operator, exactly as the metric rows carry them.

    Mirrors the union layout in ``MetricsEngine.compute_from_traces`` (metrics/engine.py): the
    stage index is the longest-path depth of the operator in the union topology over every trace
    of its pipeline (all span statuses), and the branch id is the op_id when several operators
    share that depth. Kept in lockstep by a test on the golden fixture.
    """
    parents_by_pipeline: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for trace in traces:
        for span in trace.spans:
            parents_by_pipeline[trace.pipeline_id].setdefault(span.op_id, set())
            parents_by_pipeline[trace.pipeline_id][span.op_id].update(span.parent_ids)

    layout: dict[str, tuple[int, str | None]] = {}
    for parent_map in parents_by_pipeline.values():
        cache: dict[str, int] = {}

        def union_depth(op_id: str, visiting: frozenset[str]) -> int:
            if op_id in cache:
                return cache[op_id]
            if op_id in visiting:
                return 0
            parents = [parent for parent in parent_map.get(op_id, set()) if parent in parent_map]
            value = 0 if not parents else 1 + max(union_depth(parent, visiting | {op_id}) for parent in parents)
            cache[op_id] = value
            return value

        depths = {op_id: union_depth(op_id, frozenset()) for op_id in parent_map}
        counts = Counter(depths.values())
        layout.update({op_id: (depth, None if counts[depth] == 1 else op_id) for op_id, depth in depths.items()})
    return layout


def operator_ids_from_traces(traces: Iterable[Any]) -> dict[str, str]:
    return {span.op_id: span.operator_id for trace in traces for span in trace.spans}


def selectors_need_traces(policy: ReleasePolicy | ReleasePolicyV3) -> bool:
    """v2 conversion and operator selectors need operator depths; final/query selectors do not."""
    if isinstance(policy, ReleasePolicy):
        return True
    return policy.evaluation.boundary != FINAL_RETRIEVAL or any(
        check.target.startswith(OPERATOR_SELECTOR_PREFIX) for check in policy.metrics
    )


# --------------------------------------------------------------------------- resolved structure


@dataclass(frozen=True)
class ResolvedCheck:
    id: str
    metric: str
    target: str
    direction: str
    max_regression: float
    min_paired_n: int
    estimator: str
    k: int | None
    pipeline_id: str | None
    #: run_id -> canonical ``pipeline|stageN|metric@k[|branch=..]`` key, or None when unbound.
    metric_key_by_run: dict[str, str | None]
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class ResolvedSlice:
    id: str
    field: str
    value: Any
    metric_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedPolicy:
    schema_version: int
    policy_id: str
    policy_digest: str
    evaluation: dict[str, Any]
    evidence: dict[str, Any]
    intervention: dict[str, Any]
    statistics: dict[str, Any]
    execution: dict[str, Any]
    checks: tuple[ResolvedCheck, ...]
    slices: tuple[ResolvedSlice, ...]
    #: {"code", "status", "scope", "detail", "check_id", "next_action"}
    findings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "evaluation": dict(self.evaluation),
            "evidence": dict(self.evidence),
            "intervention": dict(self.intervention),
            "statistics": dict(self.statistics),
            "execution": dict(self.execution),
            "checks": [asdict(check) for check in self.checks],
            "slices": [{**asdict(item), "metric_ids": list(item.metric_ids)} for item in self.slices],
            "findings": [dict(finding) for finding in self.findings],
        }


@dataclass(frozen=True)
class ConversionResult:
    policy: ReleasePolicyV3 | None
    unresolved: tuple[dict[str, Any], ...]
    findings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.model_dump(mode="json") if self.policy is not None else None,
            "unresolved": [dict(item) for item in self.unresolved],
            "findings": [dict(finding) for finding in self.findings],
        }


# --------------------------------------------------------------------------- resolution


def resolve_policy(
    policy: ReleasePolicy | ReleasePolicyV3,
    baseline: RunEvidence,
    candidate: RunEvidence,
) -> ResolvedPolicy:
    runs = (baseline, candidate)
    if isinstance(policy, ReleasePolicyV3):
        checks = tuple(_resolve_check(check, policy, runs) for check in policy.metrics)
        evaluation, execution = policy.evaluation.model_dump(mode="json"), policy.execution.model_dump(mode="json")
    else:
        checks = tuple(_resolve_v2_guard(guard, runs) for guard in policy.metrics)
        evaluation, execution = {}, {}
    all_ids = tuple(check.id for check in checks)
    slices = tuple(
        ResolvedSlice(item.id, item.field, item.value, tuple(getattr(item, "metric_ids", ())) or all_ids)
        for item in policy.slices
    )
    return ResolvedPolicy(
        schema_version=policy.schema_version,
        policy_id=policy.id,
        policy_digest=policy.digest or "",
        evaluation=evaluation,
        evidence=policy.evidence.model_dump(mode="json"),
        intervention=policy.intervention.model_dump(mode="json"),
        statistics=policy.statistics.model_dump(mode="json"),
        execution=execution,
        checks=checks,
        slices=slices,
        findings=tuple(_check_findings(checks)),
    )


def _check_findings(checks: Sequence[ResolvedCheck]) -> list[dict[str, Any]]:
    # A check resolved to different keys per run (topology changed) carries no finding: the
    # evaluators read each run at its own key.
    return [
        _finding(
            METRIC_SELECTOR_UNRESOLVED,
            "BLOCK",
            check.id,
            f"check {check.id} ({check.metric} at {check.target}) is {check.status}: {check.detail}",
            "Point the check at a metric both runs record: pin `pipeline`, use final_retrieval, "
            "or name one operator invocation, then rerun the comparison.",
        )
        for check in checks
        if check.status != "resolved"
    ]


def _resolve_check(check: Any, policy: ReleasePolicyV3, runs: tuple[RunEvidence, RunEvidence]) -> ResolvedCheck:
    target = check.target
    if target == FINAL_RETRIEVAL and policy.evaluation.boundary != FINAL_RETRIEVAL:
        target = policy.evaluation.boundary
    policy_k = (check.k or policy.evaluation.k) if check.metric in CUTOFF_METRICS else None
    stored_k = policy_k if policy_k is not None else 0
    outcomes = [_resolve_in_run(check.metric, target, check.pipeline, stored_k, run) for run in runs]
    pipelines = {outcome[3] for outcome in outcomes if outcome[3] is not None}
    keys = {run.run_id: outcome[0] for run, outcome in zip(runs, outcomes)}
    status, detail = _combine(runs, outcomes)
    if status == "resolved" and target != check.target:
        detail = f"evaluation.boundary {target} applied; {detail}".rstrip("; ")
    return ResolvedCheck(
        id=check.id,
        metric=check.metric,
        target=check.target,
        direction=check.direction,
        max_regression=check.max_regression,
        min_paired_n=check.min_paired_n,
        estimator=check.estimator,
        k=policy_k,
        pipeline_id=check.pipeline or (next(iter(pipelines)) if len(pipelines) == 1 else None),
        metric_key_by_run=keys,
        status=status,
        detail=detail,
    )


def _resolve_in_run(
    metric: str,
    target: str,
    pipeline: str | None,
    k: int,
    run: RunEvidence,
) -> tuple[str | None, CheckStatus, str, str | None]:
    """(key, status, detail, pipeline) for one check in one run."""
    recorded = _pipeline_ids(run)
    if pipeline is not None:
        if recorded and pipeline not in recorded:
            return None, "absent", f"pipeline {pipeline!r} is not recorded in run {run.run_id} ({', '.join(recorded)})", None
    elif len(recorded) == 1:
        pipeline = recorded[0]
    elif not recorded:
        return None, "absent", f"run {run.run_id} records no pipeline", None
    else:
        return None, "ambiguous", f"run {run.run_id} records several pipelines ({', '.join(recorded)}); set `pipeline`", None

    if target == "query":
        key = _key(pipeline, -1, _QUERY_LEVEL_STORED[metric], 0, None)
        if not _has_rows(run, pipeline, -1, _QUERY_LEVEL_STORED[metric], 0, None):
            return None, "absent", f"{key} is not recorded in run {run.run_id}", pipeline
        return key, "resolved", "", pipeline

    if target == FINAL_RETRIEVAL:
        stages = [
            int(row["stage_index"])
            for row in run.metric_rows
            if _matches(row, pipeline, None, metric, k, None) and int(row["stage_index"]) >= 0
        ]
        if not stages:
            return None, "absent", f"no {metric}@{k} rows for pipeline {pipeline!r} in run {run.run_id}", pipeline
        stage = max(stages)
        return _key(pipeline, stage, metric, k, None), "resolved", f"final output is stage {stage} in run {run.run_id}", pipeline

    operator_id = target[len(OPERATOR_SELECTOR_PREFIX):]
    if run.operator_depths is None:
        return None, "unsupported", "traces not loaded", pipeline
    slots = sorted(
        {slot for op_id, slot in run.operator_depths.items() if _names_operator(op_id, operator_id, run.operator_ids)},
        key=lambda slot: (slot[0], slot[1] or ""),
    )
    if not slots:
        return None, "absent", f"operator {operator_id!r} does not appear in run {run.run_id}'s traces", pipeline
    if len(slots) > 1:
        placed = ", ".join(f"{stage}" + (f" (branch {branch})" if branch else "") for stage, branch in slots)
        return (
            None,
            "ambiguous",
            f"operator {operator_id!r} has {len(slots)} invocations at stages {placed}; pin one or use final_retrieval",
            pipeline,
        )
    stage, branch = slots[0]
    key = _key(pipeline, stage, metric, k, branch)
    if not _has_rows(run, pipeline, stage, metric, k, branch):
        return None, "absent", f"{key} is not recorded in run {run.run_id}", pipeline
    return key, "resolved", "", pipeline


def _resolve_v2_guard(guard: MetricGuard, runs: tuple[RunEvidence, RunEvidence]) -> ResolvedCheck:
    """A v2 guard is already positional: it resolves to itself wherever the key is recorded."""
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(guard.metric)
    outcomes = []
    for run in runs:
        if _has_rows(run, pipeline_id, stage_index, metric_name, k, branch_id):
            outcomes.append((guard.metric, "resolved", "", pipeline_id))
        else:
            outcomes.append((None, "absent", f"{guard.metric} is not recorded in run {run.run_id}", pipeline_id))
    status, detail = _combine(runs, outcomes)
    return ResolvedCheck(
        id=guard.metric,
        metric=metric_name,
        target=guard.metric,
        direction=guard.direction,
        max_regression=guard.max_regression,
        min_paired_n=guard.min_paired_n,
        estimator=_latency_estimator(metric_name),
        k=k,
        pipeline_id=pipeline_id,
        metric_key_by_run={run.run_id: outcome[0] for run, outcome in zip(runs, outcomes)},
        status=status,
        detail=detail,
    )


def _combine(
    runs: tuple[RunEvidence, RunEvidence],
    outcomes: Sequence[tuple[str | None, CheckStatus, str, str | None]],
) -> tuple[CheckStatus, str]:
    unresolved = [(run, outcome) for run, outcome in zip(runs, outcomes) if outcome[1] != "resolved"]
    if unresolved:
        status = unresolved[0][1][1]
        return status, "; ".join(outcome[2] for _run, outcome in unresolved)
    keys = [outcome[0] for outcome in outcomes]
    if len(set(keys)) > 1:
        return "resolved", "runs resolve to different metric keys: " + _format_keys(
            {run.run_id: key for run, key in zip(runs, keys)}
        )
    return "resolved", "; ".join(outcome[2] for outcome in outcomes if outcome[2])


# --------------------------------------------------------------------------- evidence view


def evidence_only_v2_policy(resolved: ResolvedPolicy) -> ReleasePolicy:
    """The v2 evidence/intervention view of a v3 policy, for ``assess_evidence``.

    Its single guard is a placeholder that is never evaluated: the v3 checks are evaluated from
    the resolved structure directly. The view's digest is never the user's policy digest and must
    not be presented as one.
    """
    return _v2_policy(resolved, [MetricGuard(
        metric=_PLACEHOLDER_GUARD, direction="higher_is_better", max_regression=0.0, min_paired_n=1,
    )])


def _v2_policy(resolved: ResolvedPolicy, guards: list[MetricGuard]) -> ReleasePolicy:
    if resolved.schema_version == 2:
        evidence = EvidenceRequirements.model_validate(resolved.evidence)
    else:
        evidence = EvidenceRequirements(
            promotion=PromotionEvidenceRequirements(
                require_lineage_readiness=bool(resolved.evidence.get("require_lineage_for_decision", False)),
            ),
            require_index_encoder_compatibility=bool(
                resolved.evidence.get("require_index_encoder_compatibility", False)
            ),
        )
    return ReleasePolicy(
        id=f"{resolved.policy_id}.resolved",
        schema_version=2,
        evidence=evidence,
        intervention=InterventionDeclaration.model_validate(resolved.intervention),
        statistics=StatisticsPolicy(**{name: resolved.statistics[name] for name in _STATISTICS_FIELDS}),
        metrics=guards,
        slices=[SliceGuard(id=item.id, field=item.field, value=item.value) for item in resolved.slices],
    )


# --------------------------------------------------------------------------- v2 conversion


def convert_v2_policy(policy: ReleasePolicy, baseline: RunEvidence, candidate: RunEvidence) -> ConversionResult:
    """Explicit v2 -> v3 conversion; a positional stage that cannot be mapped uniquely is reported."""
    runs = (baseline, candidate)
    checks: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, guard in enumerate(policy.metrics):
        converted, reason = _convert_guard(guard, runs)
        if converted is None:
            unresolved.append({"metric": guard.metric, "reason": reason})
            findings.append(
                _finding(
                    POLICY_SELECTOR_AMBIGUOUS,
                    "BLOCK",
                    guard.metric,
                    f"v2 selector {guard.metric} cannot be converted: {reason}",
                    "Declare the guard with a v3 selector (final_retrieval, query, or operator:<id>).",
                )
            )
            continue
        check_id = _check_id(guard.metric, index, used_ids)
        used_ids.add(check_id)
        checks.append({
            "id": check_id,
            "direction": guard.direction,
            "max_regression": guard.max_regression,
            "min_paired_n": guard.min_paired_n,
            **converted,
        })
    if not checks:
        return ConversionResult(None, tuple(unresolved), tuple(findings))

    payload = {
        "schema_version": 3,
        "id": policy.id,
        "evaluation": _evaluation_from_manifests(runs),
        "intervention": policy.intervention.model_dump(mode="json"),
        "evidence": {
            "require_index_encoder_compatibility": policy.evidence.require_index_encoder_compatibility,
            "require_lineage_for_decision": policy.evidence.promotion.require_lineage_readiness,
        },
        "statistics": {name: getattr(policy.statistics, name) for name in _STATISTICS_FIELDS},
        "metrics": checks,
        "slices": [{"id": item.id, "field": item.field, "value": item.value} for item in policy.slices],
    }
    try:
        converted_policy: ReleasePolicyV3 | None = ReleasePolicyV3.model_validate(payload)
    except ValidationError as exc:
        converted_policy = None
        findings.append(
            _finding(
                POLICY_CONVERSION_INVALID,
                "BLOCK",
                policy.id,
                f"converted v3 policy is invalid: {exc.errors()[0]['msg']}",
                "Correct the statistical configuration in the v3 policy.",
            )
        )
    return ConversionResult(converted_policy, tuple(unresolved), tuple(findings))


def _convert_guard(guard: MetricGuard, runs: tuple[RunEvidence, RunEvidence]) -> tuple[dict[str, Any] | None, str]:
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(guard.metric)
    if stage_index < 0:
        if metric_name.startswith("latency"):
            return {"metric": "latency_ms", "target": "query", "estimator": _latency_estimator(metric_name), "pipeline": pipeline_id}, ""
        if metric_name in ("failure", "failure_rate"):
            return {"metric": "failure_rate", "target": "query", "pipeline": pipeline_id}, ""
        return None, f"no v3 target for run-level metric {metric_name!r}"

    base: dict[str, Any] = {"pipeline": pipeline_id}
    if metric_name.startswith("latency"):
        base.update(metric="latency_ms", estimator=_latency_estimator(metric_name))
        stored_name, stored_k = "latency_ms", 0
    elif metric_name in CUTOFF_METRICS:
        if k < 1:
            return None, f"{metric_name} needs a cutoff k >= 1"
        base.update(metric=metric_name, k=k)
        stored_name, stored_k = metric_name, k
    elif metric_name in ("mrr", "map"):
        base.update(metric=metric_name)
        stored_name, stored_k = metric_name, 0
    else:
        return None, f"metric {metric_name!r} has no v3 equivalent"

    if branch_id is None and base["metric"] != "latency_ms" and all(
        _final_stage(run, pipeline_id, stored_name, stored_k) == stage_index for run in runs
    ):
        return {**base, "target": FINAL_RETRIEVAL}, ""

    operators = []
    for run in runs:
        if run.operator_depths is None:
            return None, f"traces not loaded for run {run.run_id}"
        matches = sorted(op_id for op_id, slot in run.operator_depths.items() if slot == (stage_index, branch_id))
        if len(matches) != 1:
            placed = ", ".join(matches) if matches else "no operator"
            return None, f"stage {stage_index}{_branch_text(branch_id)} maps to {placed} in run {run.run_id}"
        operators.append(matches[0])
    if len(set(operators)) != 1:
        return None, f"stage {stage_index}{_branch_text(branch_id)} is {operators[0]!r} in one run and {operators[1]!r} in the other"
    return {**base, "target": f"{OPERATOR_SELECTOR_PREFIX}{operators[0]}"}, ""


def _evaluation_from_manifests(runs: tuple[RunEvidence, RunEvidence]) -> dict[str, Any]:
    recorded = [run.manifest.get("evaluation") for run in runs]
    recorded = [value for value in recorded if isinstance(value, Mapping)]
    source = recorded[0] if len(recorded) == 2 and recorded[0] == recorded[1] else {}
    unit = source.get("unit") if source.get("unit") in ("document", "chunk") else "document"
    k = source.get("k") if isinstance(source.get("k"), int) and source.get("k") >= 1 else 10
    threshold = source.get("relevance_threshold")
    threshold = threshold if isinstance(threshold, int) and threshold >= 1 else 1
    return {"unit": unit, "boundary": FINAL_RETRIEVAL, "k": k, "relevance_threshold": threshold}


def _check_id(metric: str, index: int, used: set[str]) -> str:
    candidate = _ID_SANITIZE.sub("-", metric.lower())
    if not _POLICY_ID.fullmatch(candidate) or candidate in used:
        candidate = f"check-{index + 1}"
    return candidate


# --------------------------------------------------------------------------- helpers


def _pipeline_ids(run: RunEvidence) -> list[str]:
    config = run.manifest.get("normalized_config") if isinstance(run.manifest, Mapping) else None
    ids: list[str] = []
    if isinstance(config, Mapping):
        for group in ("pipelines", "graphs"):
            for entry in config.get(group) or []:
                if isinstance(entry, Mapping) and entry.get("id") is not None:
                    ids.append(str(entry["id"]))
    if not ids:
        ids = sorted({str(row["pipeline_id"]) for row in run.metric_rows if row.get("pipeline_id") is not None})
    return list(dict.fromkeys(ids))


def _matches(row: Mapping[str, Any], pipeline: str, stage: int | None, metric: str, k: int, branch: str | None) -> bool:
    return (
        row.get("pipeline_id") == pipeline
        and (stage is None or int(row.get("stage_index", -2)) == stage)
        and row.get("metric_name") == metric
        and int(row.get("k", -1)) == k
        and row.get("branch_id") == branch
    )


def _has_rows(run: RunEvidence, pipeline: str, stage: int, metric: str, k: int, branch: str | None) -> bool:
    return any(_matches(row, pipeline, stage, metric, k, branch) for row in run.metric_rows)


def _final_stage(run: RunEvidence, pipeline: str, metric: str, k: int) -> int | None:
    stages = [
        int(row["stage_index"])
        for row in run.metric_rows
        if _matches(row, pipeline, None, metric, k, None) and int(row["stage_index"]) >= 0
    ]
    return max(stages) if stages else None


def _names_operator(op_id: str, operator_id: str, operator_ids: Mapping[str, str] | None) -> bool:
    # ``op#n`` node keys are repeated invocations of ``op`` (tracing/model.next_node_id).
    return (
        op_id == operator_id
        or op_id.split("#", 1)[0] == operator_id
        or (operator_ids or {}).get(op_id) == operator_id
    )


def _key(pipeline: str, stage: int, metric: str, k: int, branch: str | None) -> str:
    key = f"{pipeline}|stage{stage}|{metric}@{k}"
    return f"{key}|branch={branch}" if branch is not None else key


def _latency_estimator(metric_name: str) -> str:
    for estimator in ("p50", "p95", "p99"):
        if metric_name.endswith(estimator):
            return estimator
    return "mean"


def _branch_text(branch_id: str | None) -> str:
    return f" (branch {branch_id})" if branch_id is not None else ""


def _format_keys(keys: Mapping[str, str | None]) -> str:
    return ", ".join(f"{run_id}={key}" for run_id, key in keys.items())


def _finding(code: str, status: str, check_id: str, detail: str, next_action: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "scope": AGGREGATE_SCOPE,
        "detail": detail,
        "check_id": check_id,
        "next_action": next_action,
    }


__all__ = [
    "METRIC_SELECTOR_UNRESOLVED",
    "POLICY_CONVERSION_INVALID",
    "POLICY_SELECTOR_AMBIGUOUS",
    "ConversionResult",
    "ResolvedCheck",
    "ResolvedPolicy",
    "ResolvedSlice",
    "RunEvidence",
    "adjusted_confidence",
    "convert_v2_policy",
    "evidence_only_v2_policy",
    "family_size",
    "minimum_resamples",
    "operator_depths_from_traces",
    "operator_ids_from_traces",
    "resolve_policy",
    "selectors_need_traces",
    "validate_bootstrap_resolution",
]
