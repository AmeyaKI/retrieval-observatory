from __future__ import annotations

import json

from typer.testing import CliRunner

from retrieval_observatory.cli import app


def test_integrate_apply_accepts_the_plan_phase_output(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("def retrieve(query): return [{'id': 'd1', 'score': 1.0}]\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    runner = CliRunner()

    db_path = tmp_path / "results.db"
    planned = runner.invoke(
        app,
        ["integrate", str(project), "--phase", "plan", "--output", str(plan_path), "--db", str(db_path)],
    )
    assert planned.exit_code == 0, planned.output
    assert json.loads(plan_path.read_text(encoding="utf-8"))["phase"] == "plan"

    applied = runner.invoke(
        app,
        ["integrate", str(project), "--phase", "apply", "--plan", str(plan_path), "--db", str(db_path)],
    )
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)["status"] == "applied"
