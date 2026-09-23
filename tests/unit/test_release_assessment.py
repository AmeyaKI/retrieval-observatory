from copy import deepcopy

import pytest
from pydantic import ValidationError

from retrieval_observatory.release.assessment import (
    PROVENANCE_IGNORED_FIELDS,
    EvidenceAssessment,
    assess_evidence,
)
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.release.readiness import ClaimReadiness

EVALUATION = {"unit": "document", "boundary": "final_retrieval", "k": 10, "relevance_threshold": 1}


def _policy(
    *,
    require_exit_reasons: bool = True,
    require_telemetry: bool = False,
    require_lineage_for_promotion: bool = False,
    equivalent_stages: list[dict] | None = None,
    expected_changes: list[str] | None = None,
    require_index_encoder_compatibility: bool = False,
) -> ReleasePolicy:
    promotion = {
        "required_manifest_fields": ["release_identity.corpus_revision"],
        "min_label_coverage": 1.0,
    }
    if require_telemetry:
        promotion["max_sampled_out_rate"] = 0.1
        promotion["max_dropped_rate"] = 0.01
    if require_lineage_for_promotion:
        promotion["require_lineage_readiness"] = True
    return ReleasePolicy.model_validate(
        {
            "id": "support-search-v2",
            "schema_version": 2,
            "evidence": {
                "promotion": promotion,
                "lineage_diagnosis": {
                    "require_stable_candidate_identity": True,
                    "min_input_output_coverage": 1.0,
                    "require_recorded_exit_reasons": require_exit_reasons,
                },
                "lineage_diff": {
                    "require_stable_candidate_identity": True,
                    "min_input_output_coverage": 1.0,
                    "require_recorded_exit_reasons": require_exit_reasons,
                    "require_topology_alignment_for_diff": True,
                    "equivalent_stages": equivalent_stages or [],
                },
                "require_index_encoder_compatibility": require_index_encoder_compatibility,
            },
            "intervention": {"expected_changes": expected_changes or []},
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 1000,
                "seed": 42,
            },
            "metrics": [
                {
                    "metric": "hybrid|stage0|recall@10",
                    "direction": "higher_is_better",
                    "max_regression": 0.01,
                    "min_paired_n": 20,
                }
            ],
        }
    )


def _manifest(
    *,
    corpus_revision: str | None = "corpus-v1",
    exit_coverage: float = 1.0,
    evaluation: dict | None = EVALUATION,
    identity: dict | None = None,
    dataset: dict | None = None,
    index_encoder: dict | None = None,
) -> dict:
    release_identity = {
        "service_id": "support-search",
        "deployment_revision": "deploy-1",
        "corpus_revision": corpus_revision,
        "index_build_id": "index-1",
        **(identity or {}),
    }
    manifest = {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels", **(dataset or {})},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "counts": {"attempted": 10, "labeled": 10},
        "release_identity": release_identity,
        "evidence_profile": {
            "release_identity": dict(release_identity),
            "run_window": {
                "started_at": "2026-07-22T12:00:00Z",
                "finished_at": "2026-07-22T12:05:00Z",
            },
            "lineage": {
                "trace_coverage": 1.0,
                "identity_continuity_coverage": 1.0,
                "document_identity_coverage": 1.0,
                "input_output_coverage": 1.0,
                "recorded_exit_reason_coverage": exit_coverage,
                "topology_edge_coverage": 1.0,
                "qrel_to_chunk_mapping_coverage": 1.0,
                "legacy_inferred_count": 0,
                "partial_trace_count": 0,
            },
            "topologies": [
                {
                    "topology_hash": "topology-a",
                    "operators": [{"op_id": "source", "op_type": "SOURCE", "parent_ids": []}],
                    "lineage_schema_versions": [1],
                }
            ],
            "telemetry": {
                "service_id": "support-search",
                "accepted": 100,
                "exported": 100,
                "dropped": 0,
                "serialization_failures": 0,
                "retries": 0,
                "permanent_failures": 0,
                "sample_rate": 1.0,
                "observed_at": "2026-07-22T12:04:00Z",
            },
        },
    }
    if evaluation is not None:
        manifest["evaluation"] = dict(evaluation)
    if index_encoder is not None:
        manifest["index_encoder"] = index_encoder
    return manifest


def _codes(readiness: ClaimReadiness) -> list[str]:
    return [finding.code for finding in readiness.findings]


def _encoder(index: str, query: str, compatible: bool | None) -> dict:
    return {
        "index_embedding_model_revision": index,
        "query_embedding_model_revision": query,
        "compatible": compatible,
    }


def test_complete_final_metrics_can_pass_promotion_while_lineage_blocks():
    baseline = _manifest(exit_coverage=0.5)
    candidate = _manifest(exit_coverage=0.5)

    assessment = assess_evidence(_policy(), baseline, candidate)

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["lineage_diagnosis"].status == "BLOCK"


def test_policy_can_make_lineage_readiness_promotion_critical():
    policy = _policy(require_lineage_for_promotion=True)
    assessment = assess_evidence(
        policy,
        _manifest(exit_coverage=0.5),
        _manifest(exit_coverage=0.5),
    )

    assert assessment.readiness["lineage_diagnosis"].status == "BLOCK"
    assert assessment.readiness["promotion"].status == "BLOCK"
    assert any(
        finding.code == "lineage_exit_reason_unrecorded"
        for finding in assessment.readiness["promotion"].findings
    )
    assert assessment.readiness["lineage_diagnosis"].findings[0].code == "lineage_exit_reason_unrecorded"


def test_required_corpus_revision_blocks_promotion():
    assessment = assess_evidence(
        _policy(require_exit_reasons=False),
        _manifest(corpus_revision=None),
        _manifest(corpus_revision="corpus-v2"),
    )

    promotion = assessment.readiness["promotion"]
    assert promotion.status == "BLOCK"
    assert any(finding.code == "required_manifest_field_missing" for finding in promotion.findings)


def test_topology_change_blocks_lineage_diff_without_blocking_promotion():
    candidate = deepcopy(_manifest())
    candidate["evidence_profile"]["topologies"][0]["topology_hash"] = "topology-b"
    candidate["evidence_profile"]["topologies"][0]["operators"][0]["op_id"] = "source-v2"

    assessment = assess_evidence(_policy(), _manifest(), candidate)

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["lineage_diff"].status == "BLOCK"
    assert any(
        finding.code == "lineage_topology_unaligned"
        for finding in assessment.readiness["lineage_diff"].findings
    )


def test_reviewed_stage_equivalence_allows_semantically_mapped_diff():
    candidate = deepcopy(_manifest())
    candidate["evidence_profile"]["topologies"][0]["topology_hash"] = "topology-b"
    candidate["evidence_profile"]["topologies"][0]["operators"][0]["op_id"] = "source-v2"

    assessment = assess_evidence(
        _policy(
            equivalent_stages=[
                {"baseline_op_id": "source", "candidate_op_id": "source-v2"}
            ]
        ),
        _manifest(),
        candidate,
    )

    assert assessment.readiness["lineage_diff"].status == "READY"


def test_missing_document_identity_coverage_blocks_lineage_diff_only():
    baseline = _manifest()
    candidate = _manifest()
    baseline["evidence_profile"]["lineage"]["document_identity_coverage"] = 0.5
    candidate["evidence_profile"]["lineage"]["document_identity_coverage"] = 1.0

    assessment = assess_evidence(_policy(), baseline, candidate)

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["lineage_diff"].status == "BLOCK"
    assert any(
        finding.code == "lineage_document_identity_partial"
        for finding in assessment.readiness["lineage_diff"].findings
    )


def test_required_telemetry_does_not_treat_absence_as_zero_loss():
    candidate = _manifest()
    candidate["evidence_profile"]["telemetry"] = None

    assessment = assess_evidence(_policy(require_telemetry=True), _manifest(), candidate)

    promotion = assessment.readiness["promotion"]
    assert promotion.status == "BLOCK"
    assert any(finding.code == "telemetry_window_unavailable" for finding in promotion.findings)


def test_comparison_identity_findings_are_json_safe():
    candidate = _manifest()
    candidate["labeling"] = {"method": "synthetic", "judge": "judge", "model": "model", "version": "1"}

    assessment = assess_evidence(_policy(), _manifest(), candidate)

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    finding = next(item for item in aggregate.findings if item.code == "comparison_identity_mismatch")
    assert finding.observed == [
        ["gold", None, None, None],
        ["synthetic", "judge", "model", "1"],
    ]


def test_changed_reranker_with_fixed_benchmark_is_eligible():
    assessment = assess_evidence(
        _policy(expected_changes=["reranker_model_revision"]),
        _manifest(identity={"reranker_model_revision": "reranker-v1"}),
        _manifest(identity={"reranker_model_revision": "reranker-v2"}),
    )

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"
    reranker = next(
        item for item in assessment.provenance.interventions
        if item.field == "release_identity.reranker_model_revision"
    )
    assert (reranker.baseline, reranker.candidate, reranker.equal) == ("reranker-v1", "reranker-v2", False)
    assert (reranker.classification, reranker.finding_code) == ("expected", None)


def test_declared_rebuilt_compatible_embedding_index_pair_is_eligible():
    baseline = _manifest(
        identity={"embedding_model_revision": "embed-v1"},
        index_encoder=_encoder("embed-v1", "embed-v1", True),
    )
    candidate = _manifest(
        identity={"embedding_model_revision": "embed-v2", "index_build_id": "index-2"},
        index_encoder=_encoder("embed-v2", "embed-v2", True),
    )

    assessment = assess_evidence(
        _policy(expected_changes=["embedding_model_revision", "index_build_id"]), baseline, candidate
    )

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"
    assert {item.field: item.classification for item in assessment.provenance.interventions if not item.equal} == {
        "release_identity.embedding_model_revision": "expected",
        "release_identity.index_build_id": "expected",
    }
    consistency = assessment.provenance.consistency
    assert [item.classification for item in consistency] == ["expected"]
    assert consistency[0].candidate == _encoder("embed-v2", "embed-v2", True)


def test_changed_query_text_under_same_ids_blocks():
    assessment = assess_evidence(
        _policy(),
        _manifest(dataset={"query_input_hash": "inputs-a"}),
        _manifest(dataset={"query_input_hash": "inputs-b"}),
    )

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    finding = next(item for item in aggregate.findings if item.code == "query_input_mismatch")
    assert finding.observed == ["inputs-a", "inputs-b"]
    assert "dataset.query_input_hash" in finding.detail
    assert "query_input_mismatch" in _codes(assessment.readiness["promotion"])
    comparison = next(item for item in assessment.provenance.invariants if item.field == "dataset.query_input_hash")
    assert (comparison.classification, comparison.finding_code) == ("evidence_invalid", "query_input_mismatch")


def test_missing_qrel_identity_blocks_instead_of_assuming_equality():
    assessment = assess_evidence(_policy(), _manifest(), _manifest(dataset={"qrel_hash": None}))

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    finding = next(item for item in aggregate.findings if item.code == "required_manifest_field_missing")
    assert finding.observed == [None, None]
    assert "candidate" in finding.detail
    assert "dataset.qrel_hash" in finding.required
    comparison = next(item for item in assessment.provenance.invariants if item.field == "dataset.judgment_digest")
    assert comparison.classification == "unknown"


def test_judgment_digest_supersedes_qrel_hash_when_both_runs_record_it():
    assessment = assess_evidence(
        _policy(),
        _manifest(dataset={"judgment_digest": "judgments-a"}),
        _manifest(dataset={"judgment_digest": "judgments-b"}),
    )

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert _codes(aggregate) == ["judgment_identity_mismatch"]
    assert aggregate.findings[0].observed == ["judgments-a", "judgments-b"]


def test_incompatible_index_encoder_blocks():
    baseline = _manifest(identity={"embedding_model_revision": "embed-v1"})
    candidate = _manifest(
        identity={"embedding_model_revision": "embed-v2"},
        index_encoder=_encoder("embed-v1", "embed-v2", False),
    )

    assessment = assess_evidence(_policy(expected_changes=["embedding_model_revision"]), baseline, candidate)

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    finding = next(item for item in aggregate.findings if item.code == "index_encoder_incompatible")
    assert finding.observed == {"run": "candidate", "index_encoder": _encoder("embed-v1", "embed-v2", False)}
    assert "index_encoder_incompatible" in _codes(assessment.readiness["promotion"])
    assert assessment.provenance.consistency[0].classification == "evidence_invalid"
    assert assessment.provenance.consistency[0].finding_code == "index_encoder_incompatible"


def test_unverified_index_encoder_holds_unless_policy_requires_compatibility():
    baseline = _manifest(
        identity={"embedding_model_revision": "embed-v1"},
        index_encoder=_encoder("embed-v1", "embed-v1", None),
    )
    candidate = _manifest(
        identity={"embedding_model_revision": "embed-v2"},
        index_encoder=_encoder("embed-v1", "embed-v2", None),
    )

    held = assess_evidence(_policy(expected_changes=["embedding_model_revision"]), baseline, candidate)
    aggregate = held.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "HOLD"
    assert _codes(aggregate) == ["index_encoder_unverified"]
    assert held.provenance.consistency[0].classification == "unknown"

    blocked = assess_evidence(
        _policy(expected_changes=["embedding_model_revision"], require_index_encoder_compatibility=True),
        baseline,
        candidate,
    )
    aggregate = blocked.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    assert _codes(aggregate) == ["index_encoder_compatibility_required"]


def test_absent_index_encoder_block_is_unknown_not_a_finding():
    baseline = _manifest(identity={"embedding_model_revision": "embed-v1"})
    candidate = _manifest(identity={"embedding_model_revision": "embed-v1"})

    assessment = assess_evidence(_policy(), baseline, candidate)

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"
    assert assessment.provenance.consistency[0].classification == "unknown"
    assert assessment.provenance.consistency[0].finding_code is None
    assert {"baseline.index_encoder", "candidate.index_encoder"} <= set(assessment.provenance.unknown_fields)

    required = assess_evidence(_policy(require_index_encoder_compatibility=True), baseline, candidate)
    aggregate = required.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    assert _codes(aggregate) == ["index_encoder_compatibility_required"] * 2


def test_runs_without_an_index_encoder_pair_have_no_consistency_entry():
    assessment = assess_evidence(_policy(require_index_encoder_compatibility=True), _manifest(), _manifest())

    assert assessment.provenance.consistency == []
    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"


def test_unsupported_corpus_change_blocks_and_cannot_be_declared():
    assessment = assess_evidence(_policy(), _manifest(corpus_revision="corpus-v1"), _manifest(corpus_revision="corpus-v2"))

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    finding = next(item for item in aggregate.findings if item.code == "corpus_identity_mismatch")
    assert finding.observed == ["corpus-v1", "corpus-v2"]
    assert "release_identity.corpus_revision" in finding.detail
    assert "corpus_identity_mismatch" in _codes(assessment.readiness["promotion"])
    with pytest.raises(ValidationError, match="expected changes must name one of"):
        _policy(expected_changes=["corpus_revision"])


def test_changed_corpus_content_blocks_even_under_an_equal_revision():
    assessment = assess_evidence(_policy(), _manifest(), _manifest(dataset={"corpus_hash": "corpus-changed"}))

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert _codes(aggregate) == ["corpus_identity_mismatch"]
    assert "dataset.corpus_hash" in aggregate.findings[0].detail


def test_undeclared_valid_intervention_holds_for_review():
    assessment = assess_evidence(
        _policy(),
        _manifest(identity={"embedding_model_revision": "embed-v1"}),
        _manifest(identity={"embedding_model_revision": "embed-v2"}),
    )

    promotion = assessment.readiness["promotion"]
    assert promotion.status == "HOLD"
    finding = next(item for item in promotion.findings if item.code == "undeclared_intervention")
    assert finding.status == "HOLD"
    assert finding.observed == {"embedding_model_revision": ["embed-v1", "embed-v2"]}
    assert "intervention.expected_changes" in finding.next_action
    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"


def test_no_policy_records_every_material_difference_as_unexpected():
    assessment = assess_evidence(
        None,
        _manifest(identity={"chunking_revision": "chunk-1"}),
        _manifest(identity={"chunking_revision": "chunk-2"}),
    )

    promotion = assessment.readiness["promotion"]
    assert promotion.status == "HOLD"
    assert _codes(promotion) == ["undeclared_intervention"]
    assert promotion.findings[0].observed == {"chunking_revision": ["chunk-1", "chunk-2"]}


def test_retriever_configuration_change_is_declared_through_models():
    baseline = _manifest()
    candidate = _manifest()
    baseline["models"] = [{"pipeline_id": "hybrid", "operator_id": "bm25", "type": "adapter.bm25", "model": None, "version": None}]
    candidate["models"] = [{"pipeline_id": "hybrid", "operator_id": "bm25", "type": "adapter.bm25", "model": None, "version": "2"}]

    undeclared = assess_evidence(_policy(), baseline, candidate)
    assert _codes(undeclared.readiness["promotion"]) == ["undeclared_intervention"]
    assert list(undeclared.readiness["promotion"].findings[0].observed) == ["retriever_configuration"]

    declared = assess_evidence(_policy(expected_changes=["retriever_configuration"]), baseline, candidate)
    assert declared.readiness["promotion"].status == "READY"
    assert next(item for item in declared.provenance.interventions if item.field == "models").classification == "expected"


def test_deployment_revision_change_is_always_expected():
    assessment = assess_evidence(_policy(), _manifest(), _manifest(identity={"deployment_revision": "deploy-2"}))

    assert assessment.readiness["promotion"].status == "READY"
    deployment = next(
        item for item in assessment.provenance.interventions
        if item.field == "release_identity.deployment_revision"
    )
    assert (deployment.baseline, deployment.candidate, deployment.classification) == ("deploy-1", "deploy-2", "expected")


def test_one_sided_intervention_field_is_unknown_not_a_finding():
    assessment = assess_evidence(_policy(), _manifest(), _manifest(identity={"reranker_model_revision": "reranker-v2"}))

    assert assessment.readiness["promotion"].status == "READY"
    reranker = next(
        item for item in assessment.provenance.interventions
        if item.field == "release_identity.reranker_model_revision"
    )
    assert (reranker.baseline, reranker.candidate, reranker.classification) == (None, "reranker-v2", "unknown")
    assert "baseline.release_identity.reranker_model_revision" in assessment.provenance.unknown_fields


def test_evaluation_k_mismatch_blocks():
    assessment = assess_evidence(_policy(), _manifest(), _manifest(evaluation={**EVALUATION, "k": 20}))

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    assert _codes(aggregate) == ["evaluation_semantics_mismatch"]
    finding = aggregate.findings[0]
    assert finding.observed == [EVALUATION, {**EVALUATION, "k": 20}]
    assert finding.detail.endswith("k.")


def test_unrecorded_evaluation_semantics_hold_for_older_runs():
    assessment = assess_evidence(_policy(), _manifest(evaluation=None), _manifest(evaluation=None))

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "HOLD"
    assert _codes(aggregate) == ["evaluation_semantics_unrecorded"]
    assert aggregate.findings[0].status == "HOLD"
    assert assessment.readiness["promotion"].status == "READY"
    assert {"baseline.evaluation", "candidate.evaluation"} <= set(assessment.provenance.unknown_fields)


def test_one_sided_evaluation_record_blocks_and_names_the_missing_side():
    assessment = assess_evidence(_policy(), _manifest(), _manifest(evaluation=None))

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    assert _codes(aggregate) == ["evaluation_semantics_missing"]
    assert "candidate" in aggregate.findings[0].detail


def test_metric_implementation_is_compared_only_when_both_runs_record_it():
    baseline = _manifest()
    baseline["metric_versions"] = {"ndcg": "gain-v1"}

    one_sided = assess_evidence(_policy(), baseline, _manifest())
    assert one_sided.readiness["aggregate_or_slice_evaluation"].status == "READY"
    assert "candidate.metric_versions" in one_sided.provenance.unknown_fields

    candidate = _manifest()
    candidate["metric_versions"] = {"ndcg": "gain-v2"}
    both = assess_evidence(_policy(), baseline, candidate)
    aggregate = both.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    assert _codes(aggregate) == ["metric_implementation_mismatch"]


def test_topology_change_does_not_block_aggregate_evaluation_of_final_outcomes():
    candidate = deepcopy(_manifest())
    candidate["evidence_profile"]["topologies"][0]["topology_hash"] = "topology-b"
    candidate["evidence_profile"]["topologies"][0]["operators"] = [
        {"op_id": "source", "op_type": "SOURCE", "parent_ids": []},
        {"op_id": "rerank", "op_type": "RERANK", "parent_ids": ["source"]},
    ]

    assessment = assess_evidence(_policy(), _manifest(), candidate)

    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"
    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["lineage_diff"].status == "BLOCK"


def test_ignored_provenance_fields_never_produce_findings():
    baseline = _manifest()
    candidate = _manifest()
    for field in PROVENANCE_IGNORED_FIELDS:
        baseline[field] = f"{field}-baseline"
        candidate[field] = f"{field}-candidate"

    assessment = assess_evidence(_policy(), baseline, candidate)

    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["aggregate_or_slice_evaluation"].status == "READY"
    recorded = {
        item.field
        for group in (assessment.provenance.invariants, assessment.provenance.interventions, assessment.provenance.consistency)
        for item in group
    }
    assert not recorded & set(PROVENANCE_IGNORED_FIELDS)


def test_provenance_assessment_defaults_and_serialises():
    readiness = {
        scope: ClaimReadiness(scope=scope, status="READY", findings=[])
        for scope in (
            "promotion",
            "aggregate_or_slice_evaluation",
            "lineage_diagnosis",
            "lineage_diff",
            "production_trace",
        )
    }
    assert EvidenceAssessment(readiness=readiness).provenance.model_dump() == {
        "invariants": [],
        "interventions": [],
        "consistency": [],
        "unknown_fields": [],
    }

    payload = assess_evidence(_policy(), _manifest(), _manifest()).model_dump(mode="json")["provenance"]
    assert {item["field"] for item in payload["invariants"]} == {
        "dataset.query_hash",
        "dataset.qrel_hash",
        "release_identity.corpus_revision",
        "dataset.corpus_hash",
        "labeling",
        "evaluation",
    }
    assert all(item["classification"] == "invariant" and item["equal"] for item in payload["invariants"])
    assert {item["field"] for item in payload["interventions"]} == {
        "release_identity.index_build_id",
        "release_identity.deployment_revision",
    }


def test_incomplete_qrel_chunk_mapping_blocks_supported_lineage_claims():
    candidate = _manifest()
    candidate["evidence_profile"]["lineage"]["qrel_to_chunk_mapping_coverage"] = 0.5

    assessment = assess_evidence(_policy(require_exit_reasons=False), _manifest(), candidate)

    diagnosis = assessment.readiness["lineage_diagnosis"]
    assert diagnosis.status == "BLOCK"
    assert any(finding.code == "qrel_to_chunk_mapping_incomplete" for finding in diagnosis.findings)


def test_sampled_production_capture_is_partial_not_ready():
    candidate = _manifest()
    candidate["evidence_profile"]["telemetry"]["sample_rate"] = 0.5

    assessment = assess_evidence(_policy(), _manifest(), candidate)

    production = assessment.readiness["production_trace"]
    assert production.status == "HOLD"
    assert any(finding.code == "production_trace_partial" for finding in production.findings)


def test_zero_telemetry_observations_do_not_establish_a_zero_drop_rate():
    candidate = _manifest()
    candidate["evidence_profile"]["telemetry"]["accepted"] = 0

    assessment = assess_evidence(_policy(require_telemetry=True), _manifest(), candidate)

    promotion = assessment.readiness["promotion"]
    assert promotion.status == "BLOCK"
    assert any(finding.code == "telemetry_dropped_rate_unavailable" for finding in promotion.findings)


def test_absent_topology_does_not_establish_lineage_alignment():
    baseline = _manifest()
    candidate = _manifest()
    baseline["evidence_profile"]["topologies"] = []
    candidate["evidence_profile"]["topologies"] = []

    assessment = assess_evidence(_policy(), baseline, candidate)

    diff = assessment.readiness["lineage_diff"]
    assert diff.status == "BLOCK"
    assert any(finding.code == "lineage_topology_unaligned" for finding in diff.findings)


def test_assessment_returns_every_claim_scope():
    assessment = assess_evidence(_policy(), _manifest(), _manifest())

    assert set(assessment.readiness) == {
        "promotion",
        "aggregate_or_slice_evaluation",
        "lineage_diagnosis",
        "lineage_diff",
        "production_trace",
    }
