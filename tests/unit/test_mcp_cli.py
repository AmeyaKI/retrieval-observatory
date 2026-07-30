from typer.testing import CliRunner

from retrieval_observatory.cli import app

runner = CliRunner()


def test_integrate_rejects_removed_framework_option():
    result = runner.invoke(app, ["integrate", "--framework", "http"])
    assert result.exit_code != 0
    assert "No such option" in result.output


def test_doctor_command_is_removed():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_mcp_and_classifier_subcommands_are_registered_and_help_works():
    for name in ("mcp", "classifier"):
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0, result.output
        assert "No such command" not in result.output
