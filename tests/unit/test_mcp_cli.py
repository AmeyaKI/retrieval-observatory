from typer.testing import CliRunner

from retrieval_observatory.cli import app

runner = CliRunner()


def test_integrate_cmd_prints_snippet():
    result = runner.invoke(app, ["integrate", "--framework", "http"])
    assert result.exit_code == 0
    assert "adapter.http" in result.stdout


def test_doctor_cmd_runs():
    result = runner.invoke(app, ["doctor"])
    assert "retrieval_observatory import" in result.stdout
