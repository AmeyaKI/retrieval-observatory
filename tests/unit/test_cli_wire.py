"""CLI retobs wire."""
from typer.testing import CliRunner

from retrieval_observatory.cli import app

runner = CliRunner()


def test_wire_cmd_setup(tmp_path):
    result = runner.invoke(app, ["wire", str(tmp_path), "--framework", "python"])
    assert result.exit_code == 0
    assert "retobs integrate . --plan" in result.stdout
    assert "retobs verify ." in result.stdout
    assert "setup_complete" in result.stdout
    assert (tmp_path / "RETOS.md").exists()


def test_top_level_help_uses_task_taxonomy_and_hides_legacy_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "evaluate",
        "report",
        "compare",
        "serve",
        "integrate",
        "verify",
        "inspect-query",
        "demo",
        "testsets",
        "production",
    ):
        assert command in result.stdout
    for legacy in ("forge", "tracelens", "advisor", "classifier", "mcp"):
        assert legacy not in result.stdout.lower()


def test_legacy_task_groups_name_exact_replacements():
    forge = runner.invoke(app, ["forge", "scan", "--help"])
    assert "retobs testsets" in forge.stdout
    assert "removed in v1.0" in forge.stdout

    production = runner.invoke(app, ["tracelens", "stats", "--help"])
    assert "retobs production" in production.stdout
    assert "removed in v1.0" in production.stdout


def test_integrate_plan_does_not_write(tmp_path):
    (tmp_path / "app.py").write_text("def retrieve(q): return []\n", encoding="utf-8")
    result = runner.invoke(app, ["integrate", str(tmp_path), "--plan"])
    assert result.exit_code == 0
    assert '"status": "planned"' in result.stdout
    assert not (tmp_path / ".retobs").exists()


def test_evaluate_callable_without_yaml_and_render_report(tmp_path):
    module = tmp_path / "retriever.py"
    module.write_text(
        "CORPUS = {'d1': 'cats', 'd2': 'dogs'}\n"
        "QUERIES = [{'query_id': 'q1', 'text': 'cats', 'relevant_doc_ids': ['d1']}]\n"
        "def retrieve(query):\n"
        "    return ['d1']\n",
        encoding="utf-8",
    )
    db = tmp_path / "results.db"
    artifact = tmp_path / "report.html"
    result = runner.invoke(app, [
        "evaluate", f"{module}:retrieve", "--db", str(db), "--format", "html", "--output", str(artifact),
    ])
    assert result.exit_code == 0, result.stdout
    assert "Verdict:" in result.stdout
    assert artifact.read_text(encoding="utf-8").startswith("<!doctype html>")

    import sqlite3

    with sqlite3.connect(db) as connection:
        run_id = connection.execute("SELECT run_id FROM runs").fetchone()[0]
    rendered = runner.invoke(app, ["report", run_id, "--db", str(db), "--format", "json"])
    assert rendered.exit_code == 0
    assert '"schema_version": 1' in rendered.stdout


def test_wire_cmd_verify(tmp_path):
    runner.invoke(app, ["wire", str(tmp_path), "--framework", "python"])
    result = runner.invoke(app, ["wire", str(tmp_path), "--verify"])
    assert result.exit_code == 1
    assert "not_verified" in result.stdout
