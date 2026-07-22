from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from retrieval_observatory.metrics.comparison import REQUIRED_COMPARISON_AXES, comparison_validity
from retrieval_observatory.release.evidence import EvidenceProfile
from retrieval_observatory.release.policy import EvidenceRequirements, LineageRequirements, ReleasePolicy
from retrieval_observatory.release.readiness import ClaimReadiness, ClaimScope, EvidenceFinding


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    readiness: dict[ClaimScope, ClaimReadiness]


def assess_evidence(
    policy: ReleasePolicy | None,
    baseline_manifest: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
) -> EvidenceAssessment:
    manifests = (baseline_manifest, candidate_manifest)
    profiles = tuple(_profile(manifest) for manifest in manifests)
    comparison_findings = _comparison_findings(manifests)
    evidence_requirements = policy.evidence if policy is not None else EvidenceRequirements()

    promotion_findings = [
        *_for_scope(comparison_findings, "promotion"),
        *(_promotion_findings(policy, manifests, profiles) if policy is not None else []),
    ]
    if policy is not None and policy.evidence.promotion.require_lineage_readiness:
        promotion_findings.extend(
            _lineage_findings(
                profiles,
                policy.evidence.lineage_diagnosis,
                scope="promotion",
            )
        )
    aggregate_findings = _for_scope(comparison_findings, "aggregate_or_slice_evaluation")
    diagnosis_findings = _lineage_findings(
        profiles,
        evidence_requirements.lineage_diagnosis,
        scope="lineage_diagnosis",
    )
    diff_findings = _lineage_findings(
        profiles,
        evidence_requirements.lineage_diff,
        scope="lineage_diff",
        require_identity=True,
    )
    topology_signatures = tuple(_topology_signatures(profile) for profile in profiles)
    if (
        all(profile is not None for profile in profiles)
        and evidence_requirements.lineage_diff.require_topology_alignment_for_diff
        and (
            any(not signatures for signatures in topology_signatures)
            or topology_signatures[0] != topology_signatures[1]
        )
    ):
        diff_findings.append(
            _finding(
                "lineage_topology_unaligned",
                "lineage_diff",
                observed=[
                    [repr(signature) for signature in sorted(signatures)]
                    for signatures in topology_signatures
                ],
                required="equivalent operator IDs, types, and parent edges",
                detail="Baseline and candidate topology semantics are not aligned for a stage-level diff.",
                next_action="Declare a reviewed equivalent-stage mapping or inspect the paths side by side.",
            )
        )

    production_findings = _production_findings(profiles)
    readiness = {
        "promotion": _readiness("promotion", promotion_findings),
        "aggregate_or_slice_evaluation": _readiness(
            "aggregate_or_slice_evaluation", aggregate_findings
        ),
        "lineage_diagnosis": _readiness("lineage_diagnosis", diagnosis_findings),
        "lineage_diff": _readiness("lineage_diff", diff_findings),
        "production_trace": _readiness("production_trace", production_findings),
    }
    return EvidenceAssessment(readiness=readiness)


def _profile(manifest: Mapping[str, Any]) -> EvidenceProfile | None:
    value = manifest.get("evidence_profile")
    if value is None:
        return None
    try:
        return EvidenceProfile.model_validate_json(json.dumps(value))
    except ValidationError:
        return None


def _comparison_findings(manifests: tuple[Mapping[str, Any], Mapping[str, Any]]) -> list[EvidenceFinding]:
    validity = comparison_validity(list(manifests))
    findings = []
    for difference in validity.differences:
        if difference.axis not in REQUIRED_COMPARISON_AXES:
            continue
        missing = difference.status == "unknown"
        findings.append(
            _finding(
                "required_manifest_field_missing" if missing else "comparison_identity_mismatch",
                "aggregate_or_slice_evaluation",
                observed=difference.values,
                required=f"equal recorded {difference.axis} values",
                detail=difference.detail,
                next_action=(
                    f"Record {difference.axis} for both runs and rerun the comparison."
                    if missing
                    else f"Compare runs with the same {difference.axis}."
                ),
            )
        )
    return findings


def _promotion_findings(
    policy: ReleasePolicy,
    manifests: tuple[Mapping[str, Any], Mapping[str, Any]],
    profiles: tuple[EvidenceProfile | None, EvidenceProfile | None],
) -> list[EvidenceFinding]:
    requirements = policy.evidence.promotion
    findings = []
    for field in requirements.required_manifest_fields:
        values = [_nested_value(manifest, field) for manifest in manifests]
        if any(value is None for value in values):
            findings.append(
                _finding(
                    "required_manifest_field_missing",
                    "promotion",
                    observed=values,
                    required=f"{field} present in both manifests",
                    detail=f"Policy-required manifest field '{field}' is missing.",
                    next_action=f"Record {field} for baseline and candidate runs.",
                )
            )

    if requirements.min_label_coverage is not None:
        coverages = [_label_coverage(manifest) for manifest in manifests]
        if any(value is None or value < requirements.min_label_coverage for value in coverages):
            findings.append(
                _finding(
                    "label_coverage_incomplete",
                    "promotion",
                    observed=coverages,
                    required=requirements.min_label_coverage,
                    detail="Observed label coverage is absent or below the promotion requirement.",
                    next_action="Add validated labels until both runs meet the declared coverage.",
                )
            )

    if requirements.max_sampled_out_rate is not None or requirements.max_dropped_rate is not None:
        telemetry = [profile.telemetry if profile is not None else None for profile in profiles]
        if any(value is None for value in telemetry):
            findings.append(
                _finding(
                    "telemetry_window_unavailable",
                    "promotion",
                    observed=[value is not None for value in telemetry],
                    required="run-window telemetry for both runs",
                    detail="Policy-required telemetry is unavailable for at least one run window.",
                    next_action="Capture instrumentation health inside each evaluation run window.",
                )
            )
            return findings

        if requirements.max_sampled_out_rate is not None:
            rates = [1.0 - value.sample_rate for value in telemetry if value is not None]
            if any(rate > requirements.max_sampled_out_rate for rate in rates):
                findings.append(
                    _finding(
                        "telemetry_sampled_out_rate_exceeded",
                        "promotion",
                        observed=rates,
                        required={"maximum": requirements.max_sampled_out_rate},
                        detail="The sampled-out trace rate exceeds the promotion limit.",
                        next_action="Increase trace sampling and rerun the evaluation.",
                    )
                )
        if requirements.max_dropped_rate is not None:
            rates = [_dropped_rate(value.accepted, value.dropped) for value in telemetry if value is not None]
            if any(rate is None for rate in rates):
                findings.append(
                    _finding(
                        "telemetry_dropped_rate_unavailable",
                        "promotion",
                        observed=rates,
                        required={"maximum": requirements.max_dropped_rate},
                        detail="The dropped trace rate cannot be established without observed trace attempts.",
                        next_action="Capture accepted or dropped trace attempts inside both run windows.",
                    )
                )
            elif any(rate > requirements.max_dropped_rate for rate in rates if rate is not None):
                findings.append(
                    _finding(
                        "telemetry_dropped_rate_exceeded",
                        "promotion",
                        observed=rates,
                        required={"maximum": requirements.max_dropped_rate},
                        detail="The dropped trace rate exceeds the promotion limit.",
                        next_action="Resolve telemetry queue or export loss and rerun the evaluation.",
                    )
                )
    return findings


def _lineage_findings(
    profiles: tuple[EvidenceProfile | None, EvidenceProfile | None],
    requirements: LineageRequirements,
    *,
    scope: ClaimScope,
    require_identity: bool = False,
) -> list[EvidenceFinding]:
    if any(profile is None for profile in profiles):
        return [
            _finding(
                "required_manifest_field_missing",
                scope,
                observed=[profile is not None for profile in profiles],
                required="valid evidence_profile in both manifests",
                detail="Lineage evidence is missing or invalid for at least one run.",
                next_action="Capture and persist a complete evidence profile for both runs.",
            )
        ]

    complete_profiles = [profile for profile in profiles if profile is not None]
    findings = []
    if requirements.require_stable_candidate_identity or require_identity:
        values = [profile.lineage.identity_continuity_coverage for profile in complete_profiles]
        if any(value is None or value < 1.0 for value in values):
            findings.append(
                _finding(
                    "lineage_identity_partial",
                    scope,
                    observed=values,
                    required=1.0,
                    detail="Stable candidate identity continuity is incomplete.",
                    next_action="Record stable candidate and logical chunk IDs across every observed stage.",
                )
            )
    if requirements.min_input_output_coverage is not None:
        values = [profile.lineage.input_output_coverage for profile in complete_profiles]
        if any(value is None or value < requirements.min_input_output_coverage for value in values):
            findings.append(
                _finding(
                    "lineage_input_output_incomplete",
                    scope,
                    observed=values,
                    required=requirements.min_input_output_coverage,
                    detail="Stage input/output coverage is absent or below the policy requirement.",
                    next_action="Capture ordered stage inputs and outputs for every declared parent edge.",
                )
            )
    if requirements.require_recorded_exit_reasons:
        values = [profile.lineage.recorded_exit_reason_coverage for profile in complete_profiles]
        if any(value is None or value < 1.0 for value in values):
            findings.append(
                _finding(
                    "lineage_exit_reason_unrecorded",
                    scope,
                    observed=values,
                    required=1.0,
                    detail="Recorded exit-reason coverage is incomplete.",
                    next_action="Instrument structured recorded exit reasons for every removed candidate.",
                )
            )
    partial_counts = [profile.lineage.partial_trace_count for profile in complete_profiles]
    if any(partial_counts):
        findings.append(
            _finding(
                "lineage_capture_partial",
                scope,
                observed=partial_counts,
                required=0,
                detail="At least one trace is truncated or has partial lineage capture.",
                next_action="Increase capture limits or repair missing parent-stage instrumentation.",
            )
        )
    qrel_coverages = [profile.lineage.qrel_to_chunk_mapping_coverage for profile in complete_profiles]
    if any(value is not None and value < 1.0 for value in qrel_coverages):
        findings.append(
            _finding(
                "qrel_to_chunk_mapping_incomplete",
                scope,
                observed=qrel_coverages,
                required=1.0,
                detail="Observed qrel-to-chunk mapping is incomplete for a lineage relevance claim.",
                next_action="Persist and validate the document-to-chunk relevance mapping for both runs.",
            )
        )
    return findings


def _production_findings(
    profiles: tuple[EvidenceProfile | None, EvidenceProfile | None],
) -> list[EvidenceFinding]:
    if any(profile is None or profile.telemetry is None for profile in profiles):
        return [
            _finding(
                "telemetry_window_unavailable",
                "production_trace",
                observed=[profile is not None and profile.telemetry is not None for profile in profiles],
                required="run-window telemetry for both runs",
                detail="Production trace health is unavailable for at least one run window.",
                next_action="Capture instrumentation health inside each run window.",
            )
        ]

    complete_profiles = [profile for profile in profiles if profile is not None]
    findings = []
    trace_coverages = [profile.lineage.trace_coverage for profile in complete_profiles]
    if any(value is None for value in trace_coverages):
        findings.append(
            _finding(
                "production_trace_coverage_unavailable",
                "production_trace",
                observed=trace_coverages,
                required=1.0,
                detail="Production trace coverage cannot be established.",
                next_action="Record expected request counts and captured traces for each run.",
            )
        )
    elif (
        any(value < 1.0 for value in trace_coverages if value is not None)
        or any(profile.telemetry is not None and profile.telemetry.sample_rate < 1.0 for profile in complete_profiles)
        or any(profile.lineage.partial_trace_count for profile in complete_profiles)
    ):
        findings.append(
            _finding(
                "production_trace_partial",
                "production_trace",
                status="HOLD",
                observed={
                    "trace_coverage": trace_coverages,
                    "sample_rate": [
                        profile.telemetry.sample_rate if profile.telemetry is not None else None
                        for profile in complete_profiles
                    ],
                    "partial_trace_count": [
                        profile.lineage.partial_trace_count for profile in complete_profiles
                    ],
                },
                required="complete, unsampled trace capture",
                detail="Production traces cover only part of the run.",
                next_action="Treat production observations as partial or increase trace sampling.",
            )
        )
    return findings


def _for_scope(findings: list[EvidenceFinding], scope: ClaimScope) -> list[EvidenceFinding]:
    return [finding.model_copy(update={"scope": scope}) for finding in findings]


def _readiness(scope: ClaimScope, findings: list[EvidenceFinding]) -> ClaimReadiness:
    status = "BLOCK" if any(finding.status == "BLOCK" for finding in findings) else "HOLD" if findings else "READY"
    return ClaimReadiness(scope=scope, status=status, findings=findings)


def _finding(
    code: str,
    scope: ClaimScope,
    *,
    observed: Any,
    required: Any,
    detail: str,
    next_action: str,
    status: str = "BLOCK",
) -> EvidenceFinding:
    return EvidenceFinding(
        code=code,
        scope=scope,
        status=status,
        observed=_json_safe(observed),
        required=_json_safe(required),
        detail=detail,
        next_action=next_action,
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _nested_value(manifest: Mapping[str, Any], path: str) -> Any:
    value: Any = manifest
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _label_coverage(manifest: Mapping[str, Any]) -> float | None:
    counts = manifest.get("counts") or {}
    attempted = counts.get("attempted")
    labeled = counts.get("labeled")
    if attempted is None or labeled is None or attempted <= 0:
        return None
    return min(float(labeled) / float(attempted), 1.0)


def _dropped_rate(accepted: int, dropped: int) -> float | None:
    attempted = accepted + dropped
    return dropped / attempted if attempted else None


def _topology_signatures(profile: EvidenceProfile | None) -> set[tuple[Any, ...]]:
    if profile is None:
        return set()
    return {
        (
            topology.topology_hash,
            tuple(
                (operator.op_id, operator.op_type, tuple(operator.parent_ids))
                for operator in topology.operators
            ),
        )
        for topology in profile.topologies
    }
