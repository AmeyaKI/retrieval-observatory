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
