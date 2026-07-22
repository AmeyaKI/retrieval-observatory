from retrieval_observatory.release.assessment import EvidenceAssessment
from retrieval_observatory.release.decision import PolicyReference, ReleaseDecision, decide_release
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.release.readiness import ClaimReadiness
from retrieval_observatory.release.statistics import GuardResult


def _policy() -> ReleasePolicy:
    return ReleasePolicy.model_validate(
        {
            "id": "release-v2",
            "schema_version": 2,
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 200,
                "seed": 7,
            },
            "metrics": [
                {
                    "metric": "pipeline|stage0|recall@10",
                    "direction": "higher_is_better",
                    "max_regression": 0.05,
                    "min_paired_n": 2,
                }
            ],
        }
    )


def _assessment(
    *, promotion: str = "READY", aggregate: str = "READY", lineage: str = "BLOCK"
) -> EvidenceAssessment:
    readiness = {
        scope: ClaimReadiness(scope=scope, status=status, findings=[])
        for scope, status in {
            "promotion": promotion,
            "aggregate_or_slice_evaluation": aggregate,
            "lineage_diagnosis": lineage,
            "lineage_diff": lineage,
            "production_trace": "READY",
        }.items()
    }
    return EvidenceAssessment(readiness=readiness)


def _guard(status: str) -> GuardResult:
    return GuardResult(
        metric="pipeline|stage0|recall@10",
        status=status,
        direction="higher_is_better",
        max_regression=0.05,
        estimator="mean",
        baseline_estimate=1.0,
        candidate_estimate=1.0,
        effect=0.0,
        ci_low=0.0,
        ci_high=0.0,
        paired_n=20,
        min_paired_n=2,
        seed=7,
        resamples=200,
        confidence_level=0.95,
        adjusted_confidence_level=0.95,
        interval_method="paired_percentile_bootstrap",
        sample_limitation=None,
    )


def test_decision_precedence_is_block_fail_hold_pass():
    policy = _policy()

    assert decide_release(policy, _assessment(promotion="BLOCK"), [_guard("FAIL")], []).status == "BLOCK"
    assert decide_release(policy, _assessment(aggregate="HOLD"), [_guard("FAIL")], []).status == "FAIL"
    assert decide_release(policy, _assessment(), [_guard("HOLD")], []).status == "HOLD"
    assert decide_release(policy, _assessment(), [_guard("PASS")], []).status == "PASS"


def test_diagnostic_block_does_not_block_promotion_pass():
    decision = decide_release(_policy(), _assessment(lineage="BLOCK"), [_guard("PASS")], [])

    assert decision.status == "PASS"
    assert decision.readiness["lineage_diagnosis"].status == "BLOCK"


def test_policyless_decision_holds_and_never_passes():
    decision = decide_release(None, _assessment(), [], [])

    assert decision.status == "HOLD"
    assert decision.policy == PolicyReference(configured=False)
    assert "release policy is required" in decision.reasons[0]


def test_substituted_guard_identity_blocks_instead_of_passing():
    wrong_guard = _guard("PASS").model_copy(update={"metric": "pipeline|stage0|ndcg@10"})

    decision = decide_release(_policy(), _assessment(), [wrong_guard], [])

    assert decision.status == "BLOCK"
    assert "required aggregate guard results are missing" in decision.reasons


def test_release_decision_is_strict_and_serializable():
    decision = decide_release(_policy(), _assessment(), [_guard("PASS")], [])

    restored = ReleaseDecision.model_validate_json(decision.model_dump_json())
    assert restored == decision
    assert restored.next_action
