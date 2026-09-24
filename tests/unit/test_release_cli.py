import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app


class _Report:
    verdict = "HOLD"
    next_action = "Collect more evidence."

    def __init__(self, verdict: str = "HOLD"):
        self.verdict = verdict
        self.audit = {"schema_version": "audit-1", "decision": {"status": verdict, "reasons": [], "exit_code": None}}

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

    assert result.exit_code == 3
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

    assert result.exit_code == 3
    assert "Deprecated" in result.stdout


def test_no_policy_hold_exits_zero_by_default(monkeypatch):
    async def fake_compare(*args, **kwargs):
        assert kwargs["policy"] is None
        return _Report()

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)

    result = CliRunner().invoke(app, ["compare", "base", "candidate"])

    assert result.exit_code == 0


@pytest.mark.parametrize(("verdict", "fail_on", "expected"), [
    ("BLOCK", "hold-or-block-or-fail", 2),
    ("FAIL", "hold-or-block-or-fail", 1),
    ("FAIL", "fail", 1),
    ("BLOCK", "fail", 0),
])
def test_gated_compare_exits_with_the_decision_code(monkeypatch, verdict, fail_on, expected):
    async def fake_compare(*args, **kwargs):
        return _Report(verdict)

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)

    result = CliRunner().invoke(app, ["compare", "base", "candidate", "--fail-on", fail_on])

    assert result.exit_code == expected


def test_artifacts_are_written_before_a_blocking_exit(monkeypatch, tmp_path):
    async def fake_compare(*args, **kwargs):
        return _Report("BLOCK")

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)
    target = tmp_path / "audit"

    result = CliRunner().invoke(
        app,
        ["compare", "base", "candidate", "--artifacts", str(target), "--fail-on", "hold-or-block-or-fail"],
    )

    assert result.exit_code == 2
    assert json.loads((target / "release-audit.json").read_text())["decision"]["status"] == "BLOCK"
    assert "BLOCK" in (target / "release-audit.html").read_text()
    assert "release-audit.html" in result.stdout


def test_invalid_fail_on_is_a_usage_error_distinct_from_block(monkeypatch):
    async def fake_compare(*args, **kwargs):
        raise AssertionError("an invalid --fail-on must not run the comparison")

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)

    result = CliRunner().invoke(app, ["compare", "base", "candidate", "--fail-on", "sometimes"])

    assert result.exit_code == 64


def test_comparison_failure_exits_70_without_artifacts(tmp_path):
    target = tmp_path / "audit"

    result = CliRunner().invoke(
        app,
        ["compare", "missing-base", "missing-candidate", "--db", str(tmp_path / "empty.db"), "--artifacts", str(target)],
    )

    assert result.exit_code == 70
    assert "Comparison failed" in result.stdout
    assert not target.exists()
