from pathlib import Path

from retrieval_observatory.release.policy import load_release_policy


ROOT = Path(__file__).resolve().parents[2]


def test_ci_release_policy_is_bounded_and_loadable() -> None:
    path = ROOT / "examples" / "ci" / "release-policy.yaml"
    policy = load_release_policy(path)

    assert policy.schema_version == 2
    assert policy.digest.startswith("sha256:")
    assert policy.metrics
    assert policy.slices
    assert all(not any(token in guard.metric for token in ("*", "SELECT", "lambda")) for guard in policy.metrics)
