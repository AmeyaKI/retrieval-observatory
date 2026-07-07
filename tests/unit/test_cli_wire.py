"""CLI retobs wire."""
from typer.testing import CliRunner

from retrieval_observatory.cli import app

runner = CliRunner()


def test_wire_cmd_setup(tmp_path):
    result = runner.invoke(app, ["wire", str(tmp_path), "--framework", "python"])
    assert result.exit_code == 0
    assert "setup_complete" in result.stdout
    assert (tmp_path / "RETOS.md").exists()


def test_wire_cmd_verify(tmp_path):
    runner.invoke(app, ["wire", str(tmp_path), "--framework", "python"])
    result = runner.invoke(app, ["wire", str(tmp_path), "--verify"])
    assert result.exit_code == 0
    assert "ready" in result.stdout
