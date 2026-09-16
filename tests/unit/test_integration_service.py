"""Verify plan handling and the failure modes an agent hits between phases."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.model import IntegrationOptions, IntegrationPhase
from retrieval_observatory.integrations.planner import build_integration_plan
from retrieval_observatory.integrations.service import NO_MANIFEST, integrate_project
from retrieval_observatory.mcp.server import _integrate_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import materialize  # noqa: E402


async def test_plan_on_missing_root_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="project root does not exist"):
        await integrate_project(tmp_path / "nope", IntegrationPhase.PLAN, IntegrationOptions())


def test_cli_reports_missing_root_without_a_traceback(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["integrate", str(tmp_path / "nope"), "--phase", "plan"])
    assert result.exit_code == 1
    assert "Integration failed" in result.output and "Traceback" not in result.output


async def test_verify_without_manifest_returns_failed_result(tmp_path: Path) -> None:
    root = materialize("proj_a", tmp_path)
    result = await integrate_project(root, IntegrationPhase.VERIFY, IntegrationOptions(db_path=str(tmp_path / "r.db")))
    assert result.status == "failed" and result.errors == (NO_MANIFEST,)
    payload = await _integrate_project(project_root=str(root), phase="verify", db_path=str(tmp_path / "r.db"))
    assert payload["errors"] == [NO_MANIFEST]


async def test_verify_with_a_different_plan_id_names_both_ids(tmp_path: Path) -> None:
    root = materialize("proj_a", tmp_path)
    plan = build_integration_plan(root)
    await integrate_project(root, IntegrationPhase.APPLY, IntegrationOptions(plan=plan))
    other = build_integration_plan(materialize("proj_b", tmp_path))
    with pytest.raises(ValueError) as excinfo:
        await integrate_project(root, IntegrationPhase.VERIFY, IntegrationOptions(plan=other, db_path=str(tmp_path / "r.db")))
    assert plan.plan_id in str(excinfo.value) and other.plan_id in str(excinfo.value)


async def test_relative_db_path_resolves_against_project_root(tmp_path: Path, monkeypatch) -> None:
    root = materialize("proj_a", tmp_path)
    plan = build_integration_plan(root)
    await integrate_project(root, IntegrationPhase.APPLY, IntegrationOptions(plan=plan))
    monkeypatch.chdir(tmp_path)
    result = await integrate_project(root, IntegrationPhase.VERIFY, IntegrationOptions(db_path="traces/results.db"))
    assert result.status == "failed"
    assert (root / "traces" / "results.db").is_file()
    assert not (tmp_path / "traces").exists()
    assert str(root / "traces" / "results.db") in result.errors[0]


def test_reapply_reports_already_applied(tmp_path: Path) -> None:
    root = materialize("proj_a", tmp_path)
    plan_path = tmp_path / "plan.json"
    runner = CliRunner()
    assert runner.invoke(app, ["integrate", str(root), "--phase", "plan", "--output", str(plan_path)]).exit_code == 0
    assert runner.invoke(app, ["integrate", str(root), "--phase", "apply", "--plan", str(plan_path)]).exit_code == 0
    again = runner.invoke(app, ["integrate", str(root), "--phase", "apply", "--plan", str(plan_path)])
    assert again.exit_code == 1
    assert "already applied (manifest present)" in again.output
    assert "stale plan" not in again.output
    assert json.loads(plan_path.read_text(encoding="utf-8"))["plan"]["plan_id"]
