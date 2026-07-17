from typer.testing import CliRunner

from retrieval_observatory.cli import app


def test_serve_defaults_to_loopback() -> None:
    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "127.0.0.1" in result.stdout
    assert "0.0.0.0" not in result.stdout
