from typer.testing import CliRunner

from retrieval_observatory.cli import app

runner = CliRunner()


def test_integrate_accepts_framework_override(tmp_path):
    (tmp_path / "search.py").write_text("def retrieve(query):\n    return []\n", encoding="utf-8")
    result = runner.invoke(app, ["integrate", str(tmp_path), "--phase", "plan", "--framework", "http"])
    assert result.exit_code == 0, result.output
    assert '"framework": "http"' in result.stdout


def test_doctor_command_is_removed():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_mcp_subcommand_is_registered_and_help_works():
    for name in ("mcp",):
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0, result.output
        assert "No such command" not in result.output
