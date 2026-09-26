"""Evidence assessment: readiness per claim scope plus a field-level provenance assessment.

Three separate checks replace blanket release-identity equality:

1. Evaluation compatibility (invariants): query inputs, relevance judgments, corpus identity
   under the fixed-corpus contract, labeling, evaluation semantics, and metric implementation
   must match. A missing required value or a mismatch BLOCKs; ``evaluation`` unrecorded on
   both runs HOLDs because older runs predate the field.
2. Declared intervention: model, index, chunking, and configuration differences are recorded
   and never block by themselves. A difference the policy does not declare in
   ``intervention.expected_changes`` HOLDs (``undeclared_intervention``) until it is declared
   or investigated. ``deployment_revision`` identifies the candidate deployment itself, so it
   is always an expected difference.
3. Within-run consistency: each run's index/query encoder pair is checked from its explicit
   ``index_encoder`` block. Differing identifiers alone cannot establish incompatibility, and
   unknown provenance stays unknown: it is listed in ``unknown_fields``, not raised as a finding,
   unless the policy sets ``evidence.require_index_encoder_compatibility``.

Identity invariants and consistency findings apply to the promotion and aggregate scopes (they
void every claim); evaluation-semantics findings apply to the aggregate scope (they govern
metric interpretation); the intervention declaration applies to the promotion scope (it governs
what is being promoted). ``PROVENANCE_IGNORED_FIELDS`` names the manifest fields that never
produce a provenance finding.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from retrieval_observatory.release.evidence import EvidenceProfile
from retrieval_observatory.release.policy import EvidenceRequirements, LineageRequirements, ReleasePolicy
from retrieval_observatory.release.readiness import (
    ClaimReadiness,
    ClaimScope,
    EvidenceFinding,
    FieldComparison,
    ProvenanceAssessment,
    ProvenanceClassification,
)


PROVENANCE_IGNORED_FIELDS = (
    "run_window",
    "python",
    "platform",
    "machine",
    "packages",
    "git_commit",
    "git_dirty",
    "environment",
    "cache_results",
    "seed",
    "output",
    "config_hash",
    "normalized_config",
)

# Evaluation invariants as (mismatch code, manifest paths, compare every recorded path). When
# ``compare_all`` is false the first path recorded on both runs is compared: a content digest
# supersedes the coarser identity it extends. Corpus identity checks the declared revision and
# the content hash whenever both runs record them. No path recorded on both runs BLOCKs.
_INVARIANTS = (
    ("query_input_mismatch", ("dataset.query_input_hash", "dataset.query_hash"), False),
    ("judgment_identity_mismatch", ("dataset.judgment_digest", "dataset.qrel_hash"), False),
    ("corpus_identity_mismatch", ("release_identity.corpus_revision", "dataset.corpus_hash"), True),
    ("comparison_identity_mismatch", ("labeling",), False),
)

# Declared-intervention field names (policy ``intervention.expected_changes``) to manifest paths.
_INTERVENTION_PATHS = {
    "reranker_model_revision": "release_identity.reranker_model_revision",
    "embedding_model_revision": "release_identity.embedding_model_revision",
    "index_build_id": "release_identity.index_build_id",
    "chunking_revision": "release_identity.chunking_revision",
    "deployment_revision": "release_identity.deployment_revision",
    "retriever_configuration": "models",
}
_ALWAYS_EXPECTED = ("deployment_revision",)
_SIDES = ("baseline", "candidate")


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    readiness: dict[ClaimScope, ClaimReadiness]
    provenance: ProvenanceAssessment = Field(default_factory=ProvenanceAssessment)


def assess_evidence(
    policy: ReleasePolicy | None,
    baseline_manifest: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
) -> EvidenceAssessment:
    manifests = (baseline_manifest, candidate_manifest)
    profiles = tuple(_profile(manifest) for manifest in manifests)
    evidence_requirements = policy.evidence if policy is not None else EvidenceRequirements()
    declared = policy.intervention.expected_changes if policy is not None else []

    comparison_findings: list[EvidenceFinding] = []
    evaluation_findings: list[EvidenceFinding] = []
    intervention_findings: list[EvidenceFinding] = []
    unknown_fields: list[str] = []
    invariants = _invariant_comparisons(manifests, comparison_findings, evaluation_findings, unknown_fields)
    interventions = _intervention_comparisons(manifests, declared, intervention_findings, unknown_fields)
    consistency = _consistency_comparisons(
        manifests,
        evidence_requirements.require_index_encoder_compatibility,
        comparison_findings,
        unknown_fields,
    )
    provenance = ProvenanceAssessment(
        invariants=invariants,
        interventions=interventions,
        consistency=consistency,
        unknown_fields=unknown_fields,
    )

    promotion_findings = [
        *_for_scope(comparison_findings, "promotion"),
        *intervention_findings,
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
    aggregate_findings = [
        *_for_scope(comparison_findings, "aggregate_or_slice_evaluation"),
        *evaluation_findings,
    ]
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
    stage_mapping = {
        mapping.candidate_op_id: mapping.baseline_op_id
        for mapping in evidence_requirements.lineage_diff.equivalent_stages
    }
    topology_signatures = (
        _topology_signatures(profiles[0]),
        _topology_signatures(profiles[1], stage_mapping),
    )
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
    return EvidenceAssessment(readiness=readiness, provenance=provenance)


def _profile(manifest: Mapping[str, Any]) -> EvidenceProfile | None:
    value = manifest.get("evidence_profile")
    if value is None:
        return None
    try:
        return EvidenceProfile.model_validate_json(json.dumps(value))
    except ValidationError:
        return None


def _invariant_comparisons(
    manifests: tuple[Mapping[str, Any], Mapping[str, Any]],
    findings: list[EvidenceFinding],
    evaluation_findings: list[EvidenceFinding],
    unknown_fields: list[str],
) -> list[FieldComparison]:
    comparisons = []
    for code, paths, compare_all in _INVARIANTS:
        recorded = [path for path in paths if all(_value(manifest, path) is not None for manifest in manifests)]
        for path in recorded if compare_all else recorded[:1]:
            values = [_value(manifest, path) for manifest in manifests]
            equal = values[0] == values[1]
            comparisons.append(_comparison(path, values, "invariant" if equal else "evidence_invalid", None if equal else code))
            if not equal:
                findings.append(
                    _finding(
                        code,
                        "aggregate_or_slice_evaluation",
                        observed=values,
                        required=f"equal recorded {path} values",
                        detail=f"Runs differ on evaluation invariant '{path}'.",
                        next_action=f"Compare runs with the same {path}.",
                    )
                )
        if not recorded:
            values = [_value(manifest, paths[0]) for manifest in manifests]
            missing = [
                side
                for side, manifest in zip(_SIDES, manifests)
                if all(_value(manifest, path) is None for path in paths)
            ] or list(_SIDES)
            comparisons.append(_comparison(paths[0], values, "unknown", "required_manifest_field_missing"))
            findings.append(
                _finding(
                    "required_manifest_field_missing",
                    "aggregate_or_slice_evaluation",
                    observed=values,
                    required=f"{' or '.join(paths)} recorded for both runs",
                    detail=f"Evaluation invariant '{paths[0]}' is not recorded for {' and '.join(missing)}.",
                    next_action=f"Record {paths[0]} for the {' and '.join(missing)} run and rerun the comparison.",
                )
            )

    versions = [_value(manifest, "metric_versions") for manifest in manifests]
    if all(value is not None for value in versions):
        equal = versions[0] == versions[1]
        code = None if equal else "metric_implementation_mismatch"
        comparisons.append(_comparison("metric_versions", versions, "invariant" if equal else "evidence_invalid", code))
        if not equal:
            findings.append(
                _finding(
                    "metric_implementation_mismatch",
                    "aggregate_or_slice_evaluation",
                    observed=versions,
                    required="equal recorded metric implementations and gain conventions",
                    detail="Runs differ on the recorded metric implementation or gain convention.",
                    next_action="Recompute both runs with the same metric implementation.",
                )
            )
    else:
        unknown_fields.extend(f"{side}.metric_versions" for side, value in zip(_SIDES, versions) if value is None)

    comparisons.append(_evaluation_semantics(manifests, evaluation_findings, unknown_fields))
    return comparisons


def _evaluation_semantics(
    manifests: tuple[Mapping[str, Any], Mapping[str, Any]],
    findings: list[EvidenceFinding],
    unknown_fields: list[str],
) -> FieldComparison:
    values = [_value(manifest, "evaluation") for manifest in manifests]
    values = [value if isinstance(value, dict) else None for value in values]
    if all(value is not None for value in values):
        differing = sorted(
            key for key in set(values[0]) | set(values[1]) if values[0].get(key) != values[1].get(key)
        )
        if differing:
            findings.append(
                _finding(
                    "evaluation_semantics_mismatch",
                    "aggregate_or_slice_evaluation",
                    observed=values,
                    required="equal evaluation unit, boundary, k, and relevance threshold",
                    detail=f"Runs differ on evaluation semantics: {', '.join(differing)}.",
                    next_action="Evaluate both runs under the same evaluation specification.",
                )
            )
        return _comparison(
            "evaluation",
            values,
            "evidence_invalid" if differing else "invariant",
            "evaluation_semantics_mismatch" if differing else None,
        )
    missing = [side for side, value in zip(_SIDES, values) if value is None]
    unknown_fields.extend(f"{side}.evaluation" for side in missing)
    if len(missing) == 1:
        findings.append(
            _finding(
                "evaluation_semantics_missing",
                "aggregate_or_slice_evaluation",
                observed=values,
                required="evaluation recorded for both runs",
                detail=f"Evaluation semantics are not recorded for the {missing[0]} run.",
                next_action=f"Rerun the {missing[0]} on a build that records the evaluation specification.",
            )
        )
        return _comparison("evaluation", values, "unknown", "evaluation_semantics_missing")
    findings.append(
        _finding(
            "evaluation_semantics_unrecorded",
            "aggregate_or_slice_evaluation",
            status="HOLD",
            observed=values,
            required="evaluation recorded for both runs",
            detail="Neither run records its evaluation semantics; both predate the evaluation record.",
            next_action="Confirm both runs used the same evaluation unit, boundary, k, and threshold, or rerun them on a build that records it.",
        )
    )
    return _comparison("evaluation", values, "unknown", "evaluation_semantics_unrecorded")


def _intervention_comparisons(
    manifests: tuple[Mapping[str, Any], Mapping[str, Any]],
    declared: list[str],
    findings: list[EvidenceFinding],
    unknown_fields: list[str],
) -> list[FieldComparison]:
    comparisons = []
    undeclared: dict[str, list[Any]] = {}
    for name, path in _INTERVENTION_PATHS.items():
        values = [_value(manifest, path) for manifest in manifests]
        values = [None if value in (None, [], {}) else value for value in values]
        if all(value is None for value in values):
            continue
        if any(value is None for value in values):
            unknown_fields.extend(f"{side}.{path}" for side, value in zip(_SIDES, values) if value is None)
            comparisons.append(_comparison(path, values, "unknown", None))
            continue
        if values[0] == values[1]:
            classification: ProvenanceClassification = "invariant"
        elif name in declared or name in _ALWAYS_EXPECTED:
            classification = "expected"
        else:
            classification = "unexpected"
            undeclared[name] = values
        comparisons.append(
            _comparison(path, values, classification, "undeclared_intervention" if classification == "unexpected" else None)
        )
    if undeclared:
        names = ", ".join(undeclared)
        findings.append(
            _finding(
                "undeclared_intervention",
                "promotion",
                status="HOLD",
                observed=undeclared,
                required="every changed intervention field declared in intervention.expected_changes",
                detail=f"Runs differ on undeclared intervention fields: {names}.",
                next_action=(
                    f"Declare {names} in the policy's intervention.expected_changes if the change is intended, "
                    "or investigate the unplanned change."
                ),
            )
        )
    return comparisons


def _consistency_comparisons(
    manifests: tuple[Mapping[str, Any], Mapping[str, Any]],
    required: bool,
    findings: list[EvidenceFinding],
    unknown_fields: list[str],
) -> list[FieldComparison]:
    """Check each run's index/query encoder pair on its own; the runs are not compared."""
    blocks = [_value(manifest, "index_encoder") for manifest in manifests]
    blocks = [block if isinstance(block, dict) else None for block in blocks]
    checked = [block is not None or _records_encoder_pair(manifest) for manifest, block in zip(manifests, blocks)]
    if not any(checked):
        return []
    statuses: list[str] = []
    codes: list[str] = []
    for side, block, applies in zip(_SIDES, blocks, checked):
        if not applies:
            continue
        if block is None:
            unknown_fields.append(f"{side}.index_encoder")
            if not required:
                statuses.append("unknown")
                continue
            code, status, detail = (
                "index_encoder_compatibility_required",
                "BLOCK",
                f"The {side} run does not record its index/query encoder pair; the policy requires it.",
            )
        else:
            compatible = block.get("compatible") if isinstance(block.get("compatible"), bool) else None
            revisions = (block.get("index_embedding_model_revision"), block.get("query_embedding_model_revision"))
            if compatible is True or (compatible is None and None not in revisions and revisions[0] == revisions[1]):
                continue
            if compatible is False:
                code, status, detail = (
                    "index_encoder_incompatible",
                    "BLOCK",
                    f"The {side} run declares its index encoder incompatible with its query encoder.",
                )
            elif required:
                code, status, detail = (
                    "index_encoder_compatibility_required",
                    "BLOCK",
                    f"The {side} run has not verified its index/query encoder compatibility; the policy requires it.",
                )
            else:
                code, status, detail = (
                    "index_encoder_unverified",
                    "HOLD",
                    f"The {side} run encodes queries and its index with different, unverified encoder revisions.",
                )
        statuses.append(status)
        codes.append(code)
        findings.append(
            _finding(
                code,
                "aggregate_or_slice_evaluation",
                status=status,
                observed={"run": side, "index_encoder": block},
                required="index_encoder.compatible true, or equal index and query encoder revisions",
                detail=detail,
                next_action="Record the index/query encoder pair with an explicit compatibility verdict for the run.",
            )
        )
    classification: ProvenanceClassification = (
        "evidence_invalid" if "BLOCK" in statuses else "unknown" if statuses else "expected"
    )
    return [_comparison("index_encoder", blocks, classification, codes[0] if codes else None)]


def _records_encoder_pair(manifest: Mapping[str, Any]) -> bool:
    return all(
        _value(manifest, path) is not None
        for path in ("release_identity.index_build_id", "release_identity.embedding_model_revision")
    )


def _comparison(
    field: str,
    values: list[Any],
    classification: ProvenanceClassification,
    finding_code: str | None,
) -> FieldComparison:
    return FieldComparison(
        field=field,
        baseline=values[0],
        candidate=values[1],
        equal=values[0] == values[1],
        classification=classification,
        finding_code=finding_code,
    )


def _value(manifest: Mapping[str, Any], path: str) -> Any:
    """A JSON-normalised manifest value; labeling is its (method, judge, model, version) tuple."""
    if path == "labeling":
        labeling = manifest.get("labeling")
        if not isinstance(labeling, Mapping) or labeling.get("method") is None:
            return None
        return _json_safe([labeling.get(key) for key in ("method", "judge", "model", "version")])
    return _json_safe(_nested_value(manifest, path))


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
    if scope == "lineage_diff":
        values = [profile.lineage.document_identity_coverage for profile in complete_profiles]
        if any(value is None or value < 1.0 for value in values):
            findings.append(
                _finding(
                    "lineage_document_identity_partial",
                    scope,
                    observed=values,
                    required=1.0,
                    detail="Stable logical-chunk and document revision/content-hash identity is incomplete.",
                    next_action="Record a document revision or content hash for every lineage candidate.",
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


def _topology_signatures(
    profile: EvidenceProfile | None,
    stage_mapping: Mapping[str, str] | None = None,
) -> set[tuple[Any, ...]]:
    if profile is None:
        return set()
    mapping = stage_mapping or {}
    return {
        tuple(
            (
                mapping.get(operator.op_id, operator.op_id),
                operator.op_type,
                tuple(sorted(mapping.get(parent, parent) for parent in operator.parent_ids)),
            )
            for operator in sorted(
                topology.operators,
                key=lambda item: mapping.get(item.op_id, item.op_id),
            )
        )
        for topology in profile.topologies
    }
