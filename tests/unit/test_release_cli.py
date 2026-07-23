from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from retrieval_observatory.cli import app


class _Report:
    verdict = "HOLD"
    next_action = "Collect more evidence."

    def to_markdown(self) -> str:
        return "# Run Comparison\n\nVerdict: HOLD\n"

    def to_json(self) -> str:
        return '{"verdict":"HOLD"}\n'

    def to_html(self) -> str:
        return "<!doctype html><p>Verdict: HOLD</p>"

    def write(self, path, *, format=None):
        return Path(path)


def test_strict_compare_exits_nonzero_for_hold(monkeypatch, tmp_path):
    captured = SimpleNamespace(policy=None)

    async def fake_compare(*args, **kwargs):
        captured.policy = kwargs["policy"]
        report = _Report()
        print(report.to_markdown())
        return report

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("id: test\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "compare",
            "base",
            "candidate",
            "--db",
            str(tmp_path / "results.db"),
            "--policy",
            str(policy_path),
            "--fail-on",
            "hold-or-block-or-fail",
        ],
    )

    assert result.exit_code == 1
    assert "Verdict: HOLD" in result.stdout
    assert captured.policy == policy_path


def test_legacy_fail_on_alias_warns_for_one_release_cycle(monkeypatch):
    async def fake_compare(*args, **kwargs):
        return _Report()

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)

    result = CliRunner().invoke(
        app,
        ["compare", "base", "candidate", "--fail-on", "regression-or-no-decision"],
    )

    assert result.exit_code == 1
    assert "Deprecated" in result.stdout


def test_no_policy_hold_exits_zero_by_default(monkeypatch):
    async def fake_compare(*args, **kwargs):
        assert kwargs["policy"] is None
        return _Report()

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)

    result = CliRunner().invoke(app, ["compare", "base", "candidate"])

    assert result.exit_code == 0
