from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from retrieval_observatory.release.assessment import EvidenceAssessment
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.release.readiness import ClaimReadiness, ClaimScope
from retrieval_observatory.release.resolution import ResolvedPolicy
from retrieval_observatory.release.slices import SliceResult
from retrieval_observatory.release.statistics import CheckResult, GuardResult, OperationalResult


DecisionStatus = Literal["PASS", "HOLD", "BLOCK", "FAIL"]
_EVIDENCE_SCOPES = ("promotion", "aggregate_or_slice_evaluation")
_NEXT_ACTION = {
    "PASS": "Review the bounded evidence and proceed through the normal deployment approval process.",
    "HOLD": "Collect more paired evidence or resolve the inconclusive guard before promotion.",
    "BLOCK": "Resolve missing or invalid required evidence, then rerun the comparison.",
    "FAIL": "Investigate the proven regression and do not promote this candidate.",
}


class PolicyReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    configured: bool
    id: str | None = None
    schema_version: int | None = None
    digest: str | None = None


class ReleaseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: DecisionStatus
    reasons: list[str]
    readiness: dict[ClaimScope, ClaimReadiness]
    aggregate_guards: list[CheckResult | GuardResult]
    slices: list[SliceResult]
    next_action: str
    policy: PolicyReference
    #: Execution accounting of a v3 evaluation; None for a v2 decision.
    operational: OperationalResult | None = None


def decide_release(
    policy: ReleasePolicy | None,
    assessment: EvidenceAssessment,
    aggregate_guards: list[GuardResult],
    slices: list[SliceResult],
) -> ReleaseDecision:
    if policy is None:
        return _decision(
            "HOLD",
            ["A release policy is required for promotion."],
            assessment,
            aggregate_guards,
            slices,
            PolicyReference(configured=False),
        )

    policy_reference = PolicyReference(
        configured=True,
        id=policy.id,
        schema_version=policy.schema_version,
        digest=policy.digest,
    )
    evidence_scopes = _EVIDENCE_SCOPES
    blocking_readiness = [
        assessment.readiness[scope]
        for scope in evidence_scopes
        if assessment.readiness[scope].status == "BLOCK"
    ]
    expected_metrics = sorted(guard.metric for guard in policy.metrics)
    missing_guards = sorted(guard.metric for guard in aggregate_guards) != expected_metrics
    expected_slice_ids = sorted(declaration.id for declaration in policy.slices)
    missing_slices = sorted(result.id for result in slices) != expected_slice_ids
    missing_slice_guards = any(
        sorted(guard.metric for guard in result.guards) != expected_metrics for result in slices
    )
    all_guard_statuses = [guard.status for guard in aggregate_guards] + [
        guard.status for result in slices for guard in result.guards
    ]
    slice_statuses = [result.status for result in slices]

    if (
        blocking_readiness
        or missing_guards
        or missing_slices
        or missing_slice_guards
        or "BLOCK" in all_guard_statuses + slice_statuses
    ):
        reasons = [
            finding.code
            for readiness in blocking_readiness
            for finding in readiness.findings
        ]
        if missing_guards:
            reasons.append("required aggregate guard results are missing")
        if missing_slices:
            reasons.append("required declared slice results are missing")
        if missing_slice_guards:
            reasons.append("required declared slice guard results are missing")
        reasons.extend(_status_reasons("BLOCK", aggregate_guards, slices))
        return _decision("BLOCK", reasons, assessment, aggregate_guards, slices, policy_reference)
    if "FAIL" in all_guard_statuses + slice_statuses:
        return _decision(
            "FAIL",
            _status_reasons("FAIL", aggregate_guards, slices),
            assessment,
            aggregate_guards,
            slices,
            policy_reference,
        )
    holding_readiness = any(
        assessment.readiness[scope].status == "HOLD" for scope in evidence_scopes
    )
    if holding_readiness or "HOLD" in all_guard_statuses + slice_statuses:
        reasons = _status_reasons("HOLD", aggregate_guards, slices)
        if holding_readiness:
            reasons.append("promotion comparison evidence is inconclusive")
        return _decision("HOLD", reasons, assessment, aggregate_guards, slices, policy_reference)
    return _decision(
        "PASS",
        ["Every declared aggregate and slice interval proves non-inferiority."],
        assessment,
        aggregate_guards,
        slices,
        policy_reference,
    )


# --------------------------------------------------------------------------- resolved (v3) decision


def decide_release_v3(
    resolved: ResolvedPolicy,
    assessment: EvidenceAssessment,
    checks: list[CheckResult],
    slices: list[SliceResult],
    operational: OperationalResult,
) -> ReleaseDecision:
    """BLOCK > FAIL > HOLD > PASS over readiness, checks, slices, and execution; every result is kept.

    Selector-resolution findings already sit in the aggregate readiness scope, so they are not
    re-listed here; the unresolved check's own BLOCK result is. Reasons name every non-PASS item.
    """
    policy_reference = PolicyReference(
        configured=True,
        id=resolved.policy_id,
        schema_version=resolved.schema_version,
        digest=resolved.policy_digest or None,
    )
    readiness = [assessment.readiness[scope] for scope in _EVIDENCE_SCOPES]
    blocking_readiness = [item for item in readiness if item.status == "BLOCK"]
    holding_readiness = [item for item in readiness if item.status == "HOLD"]

    missing = [f"check {check_id}" for check_id in _missing(resolved.checks, checks)]
    results_by_slice = {result.id: result for result in slices}
    for item in resolved.slices:
        result = results_by_slice.get(item.id)
        if result is None:
            missing.append(f"declared slice {item.id}")
        elif result.guards or result.status != "BLOCK":
            missing.extend(f"declared slice {item.id} check {check_id}" for check_id in _missing(item.metric_ids, result.guards))
    unresolved = [check for check in checks if check.resolution_status != "resolved"]
    statuses = (
        [check.status for check in checks]
        + [result.status for result in slices]
        + [guard.status for result in slices for guard in result.guards]
        + [operational.status]
    )

    reasons = [finding.code for item in blocking_readiness + holding_readiness for finding in item.findings]
    reasons.extend(f"required result is missing: {name}" for name in missing)
    reasons.extend(_check_reason(check) for check in checks if check.status != "PASS")
    reasons.extend(_slice_reason(result) for result in slices if result.status != "PASS")
    if operational.status != "PASS":
        reasons.append(f"execution: {operational.status}: {operational.detail}")

    if blocking_readiness or missing or unresolved or "BLOCK" in statuses:
        status: DecisionStatus = "BLOCK"
    elif "FAIL" in statuses:
        status = "FAIL"
    elif holding_readiness or "HOLD" in statuses:
        status = "HOLD"
    else:
        status = "PASS"
        reasons = ["Every declared check and slice interval proves non-inferiority and the candidate's failure rate is within budget."]
    return _decision(status, reasons, assessment, list(checks), slices, policy_reference, operational)


def _missing(expected: object, results: object) -> list[str]:
    expected_ids = [getattr(item, "id", item) for item in expected]  # type: ignore[union-attr]
    seen = {getattr(result, "check_id", getattr(result, "metric", None)) for result in results}  # type: ignore[union-attr]
    return [check_id for check_id in expected_ids if check_id not in seen]


def _check_reason(check: CheckResult) -> str:
    return f"check {check.check_id}: {check.status}: {_check_detail(check)}"


def _check_detail(check: CheckResult) -> str:
    if check.sample_limitation:
        return check.sample_limitation
    if check.ci_low is None or check.ci_high is None:
        return "no interval"
    boundary = -check.max_regression if check.direction == "higher_is_better" else check.max_regression
    verb = "crosses" if check.status == "HOLD" else "is wholly beyond" if check.status == "FAIL" else "clears"
    return f"interval [{check.ci_low:.4g}, {check.ci_high:.4g}] {verb} the {boundary:.4g} boundary"


def _slice_reason(result: SliceResult) -> str:
    details = [
        f"{getattr(guard, 'check_id', guard.metric)} {guard.status} ({_check_detail(guard)})"  # type: ignore[arg-type]
        for guard in result.guards
        if guard.status != "PASS"
    ]
    if result.sample_limitation and not details:
        details = [result.sample_limitation]
    return f"declared slice {result.id}: {result.status}: {'; '.join(details) or 'no detail'}"


def _status_reasons(
    status: DecisionStatus,
    aggregate_guards: list[GuardResult],
    slices: list[SliceResult],
) -> list[str]:
    reasons = [f"aggregate guard {guard.metric}: {status}" for guard in aggregate_guards if guard.status == status]
    reasons.extend(f"declared slice {result.id}: {status}" for result in slices if result.status == status)
    return reasons


def _decision(
    status: DecisionStatus,
    reasons: list[str],
    assessment: EvidenceAssessment,
    aggregate_guards: list[GuardResult],
    slices: list[SliceResult],
    policy: PolicyReference,
    operational: OperationalResult | None = None,
) -> ReleaseDecision:
    return ReleaseDecision(
        status=status,
        reasons=reasons or [f"Release decision is {status}."],
        readiness=assessment.readiness,
        aggregate_guards=aggregate_guards,
        slices=slices,
        next_action=_NEXT_ACTION[status],
        policy=policy,
        operational=operational,
    )
