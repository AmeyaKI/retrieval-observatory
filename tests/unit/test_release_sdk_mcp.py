from types import SimpleNamespace

from retrieval_observatory.mcp import server
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.sdk import api
from retrieval_observatory.sdk.report import BenchmarkReport


class _Report:
    comparison = {"release_decision": {"schema_version": 1, "status": "HOLD"}}

    def to_dict(self):
        return {"comparison": self.comparison}

    def to_markdown(self):
        return "Verdict: HOLD"

    def to_html(self):
        return "<!doctype html><p>Verdict: HOLD</p>"


def _policy() -> ReleasePolicy:
    return ReleasePolicy.model_validate(
        {
            "id": "sdk-policy-v2",
            "schema_version": 2,
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 100,
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


def test_sdk_compare_accepts_validated_policy(monkeypatch):
    captured = {}

    async def fake_load(baseline, candidate, db_path, *, policy=None):
        captured.update(policy=policy, baseline=baseline, candidate=candidate)
        return _Report()

    monkeypatch.setattr("retrieval_observatory.sdk.report.load_comparison_report", fake_load)
    policy = _policy()

    report = api.compare("base", "candidate", policy=policy)

    assert report.to_dict() == _Report().to_dict()
    assert captured == {"policy": policy, "baseline": "base", "candidate": "candidate"}


def test_benchmark_report_compare_reuses_canonical_artifact(monkeypatch):
    captured = {}

    async def fake_load(baseline, candidate, db_path, *, policy=None):
        captured.update(policy=policy, baseline=baseline, candidate=candidate, db_path=db_path)
        return _Report()

    monkeypatch.setattr("retrieval_observatory.sdk.report.load_comparison_report", fake_load)
    baseline = BenchmarkReport(SimpleNamespace(run_id="base"), "results.db", "base")
    candidate = BenchmarkReport(SimpleNamespace(run_id="candidate"), "results.db", "candidate")
    policy = _policy()

    payload = candidate.compare(baseline, policy=policy)

    assert payload == _Report.comparison
    assert captured == {
        "policy": policy,
        "baseline": "base",
        "candidate": "candidate",
        "db_path": "results.db",
    }


async def test_mcp_compare_accepts_only_explicit_local_policy_path(monkeypatch, tmp_path):
    captured = {}

    async def fake_load(baseline, candidate, db_path, *, policy=None):
        captured.update(policy=policy, baseline=baseline, candidate=candidate)
        return _Report()

    monkeypatch.setattr("retrieval_observatory.sdk.report.load_comparison_report", fake_load)
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("id: local\n", encoding="utf-8")

    payload = await server._compare_runs(
        "base",
        "candidate",
        policy_path=str(policy_path),
    )

    assert payload == _Report().to_dict()
    assert captured["policy"] == str(policy_path)
