from copy import deepcopy

from retrieval_observatory.release.assessment import assess_evidence
from retrieval_observatory.release.policy import ReleasePolicy


def _policy(
    *,
    require_exit_reasons: bool = True,
    require_telemetry: bool = False,
    require_lineage_for_promotion: bool = False,
    equivalent_stages: list[dict] | None = None,
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
            },
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


def _manifest(*, corpus_revision: str | None = "corpus-v1", exit_coverage: float = 1.0) -> dict:
    return {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "counts": {"attempted": 10, "labeled": 10},
        "release_identity": {
            "service_id": "support-search",
            "deployment_revision": "deploy-1",
            "corpus_revision": corpus_revision,
            "index_build_id": "index-1",
        },
        "evidence_profile": {
            "release_identity": {
                "service_id": "support-search",
                "deployment_revision": "deploy-1",
                "corpus_revision": corpus_revision,
                "index_build_id": "index-1",
            },
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


def test_release_identity_mismatch_blocks_promotion_and_aggregate_evaluation():
    candidate = _manifest()
    candidate["release_identity"]["embedding_model_revision"] = "embed-v2"
    baseline = _manifest()
    baseline["release_identity"]["embedding_model_revision"] = "embed-v1"

    assessment = assess_evidence(_policy(), baseline, candidate)

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    finding = next(item for item in aggregate.findings if item.code == "release_identity_mismatch")
    assert finding.observed == ["embed-v1", "embed-v2"]
    assert "embedding_model_revision" in finding.detail

    promotion = assessment.readiness["promotion"]
    assert promotion.status == "BLOCK"
    assert any(item.code == "release_identity_mismatch" for item in promotion.findings)


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
