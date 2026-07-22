from pathlib import Path

import pytest
from pydantic import ValidationError

from retrieval_observatory.release import (
    ClaimReadiness,
    EvidenceFinding,
    ReleasePolicy,
    load_release_policy,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "release_policy.yaml"


def _metric(**changes):
    metric = {
        "metric": "hybrid__rerank|stage1|ndcg@10",
        "direction": "higher_is_better",
        "max_regression": 0.01,
        "min_paired_n": 100,
    }
    metric.update(changes)
    return metric


def _statistics(**changes):
    statistics = {
        "confidence_level": 0.95,
        "familywise_alpha": 0.05,
        "resamples": 10000,
        "seed": 42,
    }
    statistics.update(changes)
    return statistics


def _policy(**changes):
    policy = {
        "id": "support-search-v2",
        "schema_version": 2,
        "statistics": _statistics(),
        "metrics": [_metric()],
    }
    policy.update(changes)
    return policy


def test_policy_separates_promotion_from_lineage_requirements():
    policy = load_release_policy(FIXTURE)

    assert policy.id == "support-search-v2"
    assert policy.digest.startswith("sha256:")
    assert policy.evidence.promotion.min_label_coverage == 0.95
    assert policy.evidence.lineage_diagnosis.require_recorded_exit_reasons is True
    assert policy.evidence.lineage_diff.require_recorded_exit_reasons is False


def test_policy_digest_is_serializable_and_integrity_checked():
    policy = load_release_policy(FIXTURE)

    assert ReleasePolicy.model_validate(policy.model_dump()).digest == policy.digest
    with pytest.raises(ValidationError, match="policy digest does not match"):
        ReleasePolicy.model_validate({**policy.model_dump(), "digest": "sha256:" + "0" * 64})


def test_policy_rejects_dynamic_metric_and_nested_slice_selectors():
    with pytest.raises(ValidationError, match="exact canonical metric key"):
        ReleasePolicy.model_validate(_policy(metrics=[{"metric": "ndcg.*", "direction": "higher_is_better"}]))

    with pytest.raises(ValidationError, match="top-level"):
        ReleasePolicy.model_validate(
            _policy(slices=[{"id": "enterprise", "field": "account.tier", "value": "pro"}])
        )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "Support Search"}, "policy id"),
        ({"schema_version": 1}, "schema_version"),
        ({"metrics": [_metric(max_regression=-0.01)]}, "greater than or equal to 0"),
        ({"metrics": [_metric(max_regression=float("inf"))]}, "finite number"),
        ({"statistics": _statistics(confidence_level=1.0)}, "less than 1"),
        ({"unexpected": True}, "Extra inputs are not permitted"),
    ],
)
def test_policy_rejects_unbounded_or_unknown_values(change, message):
    with pytest.raises(ValidationError, match=message):
        ReleasePolicy.model_validate(_policy(**change))


def test_policy_rejects_duplicate_guard_identities():
    with pytest.raises(ValidationError, match="metric guard identities must be unique"):
        ReleasePolicy.model_validate(_policy(metrics=[_metric(), _metric(direction="lower_is_better")]))

    duplicate_slice = {"id": "enterprise", "field": "tier", "value": "pro"}
    with pytest.raises(ValidationError, match="slice guard identities must be unique"):
        ReleasePolicy.model_validate(_policy(slices=[duplicate_slice, duplicate_slice]))


def test_promotion_requirements_cannot_implicitly_require_lineage():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReleasePolicy.model_validate(
            _policy(evidence={"promotion": {"require_recorded_exit_reasons": True}})
        )


def test_claim_readiness_uses_scoped_non_release_statuses():
    finding = EvidenceFinding(
        code="lineage_exit_reason_unrecorded",
        scope="lineage_diagnosis",
        status="BLOCK",
        observed=0.5,
        required=0.99,
        detail="Recorded exit coverage is below the policy requirement.",
        next_action="Capture recorded exit reasons for retrieval stages.",
    )

    readiness = ClaimReadiness(scope="lineage_diagnosis", status="BLOCK", findings=[finding])

    assert readiness.findings == [finding]
    with pytest.raises(ValidationError):
        ClaimReadiness(scope="lineage_diagnosis", status="FAIL", findings=[])
