from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from retrieval_observatory.release.assessment import EvidenceAssessment
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.release.readiness import ClaimReadiness, ClaimScope
from retrieval_observatory.release.slices import SliceResult
from retrieval_observatory.release.statistics import GuardResult


DecisionStatus = Literal["PASS", "HOLD", "BLOCK", "FAIL"]


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
    aggregate_guards: list[GuardResult]
    slices: list[SliceResult]
    next_action: str
    policy: PolicyReference


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
    evidence_scopes = ("promotion", "aggregate_or_slice_evaluation")
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
) -> ReleaseDecision:
    return ReleaseDecision(
        status=status,
        reasons=reasons or [f"Release decision is {status}."],
        readiness=assessment.readiness,
        aggregate_guards=aggregate_guards,
        slices=slices,
        next_action={
            "PASS": "Review the bounded evidence and proceed through the normal deployment approval process.",
            "HOLD": "Collect more paired evidence or resolve the inconclusive guard before promotion.",
            "BLOCK": "Resolve missing or invalid required evidence, then rerun the comparison.",
            "FAIL": "Investigate the proven regression and do not promote this candidate.",
        }[status],
        policy=policy,
    )
