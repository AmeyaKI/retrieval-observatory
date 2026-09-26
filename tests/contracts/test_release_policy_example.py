from pathlib import Path

from retrieval_observatory.release.policy import ReleasePolicy, ReleasePolicyV3, load_release_policy


ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_TOKENS = ("*", "SELECT", "lambda", "{", "$")


def test_ci_release_policy_is_bounded_and_loadable() -> None:
    path = ROOT / "examples" / "ci" / "release-policy.yaml"
    policy = load_release_policy(path)

    assert isinstance(policy, ReleasePolicy)
    assert policy.schema_version == 2
    assert policy.digest.startswith("sha256:")
    assert policy.metrics
    assert policy.slices
    assert all(not any(token in guard.metric for token in DYNAMIC_TOKENS) for guard in policy.metrics)


def test_ci_release_policy_v3_is_bounded_and_loadable() -> None:
    path = ROOT / "examples" / "ci" / "release-policy-v3.yaml"
    policy = load_release_policy(path)

    assert isinstance(policy, ReleasePolicyV3)
    assert policy.schema_version == 3
    assert policy.digest.startswith("sha256:")
    assert policy.metrics
    assert policy.slices and policy.slices[0].metric_ids == ["final-recall"]
    assert all(
        not any(token in check.target for token in DYNAMIC_TOKENS) for check in policy.metrics
    )
    assert all(
        check.target in ("final_retrieval", "query") or check.target.startswith("operator:")
        for check in policy.metrics
    )


def test_v2_and_v3_examples_have_distinct_digests() -> None:
    v2 = load_release_policy(ROOT / "examples" / "ci" / "release-policy.yaml")
    v3 = load_release_policy(ROOT / "examples" / "ci" / "release-policy-v3.yaml")

    assert v2.digest != v3.digest
