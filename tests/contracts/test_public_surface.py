from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner
from typer.main import get_command

import retrieval_observatory as ro
from retrieval_observatory.cli import app
from retrieval_observatory.mcp.server import build_server


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
REMOVED = {
    "advisor",
    "benchmark_config",
    "benchmark_config_file",
    "benchmark_pipeline_descriptor",
    "benchmark_vs_baseline",
    "bootstrap" + "_project",
    "forge",
    "get_pareto_frontier",
    "get_pipeline_diagram",
    "get_recommendations",
    "plan" + "_integration",
    "quickstart",
    "run",
    "tracelens",
    "wire",
    "wire" + "_project",
}


def _mcp_tool_names() -> set[str]:
    tools = build_server().list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    return {tool.name for tool in tools}


def test_cli_help_matches_contract_exactly() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout
    commands = set(get_command(app).commands)
    assert commands == set(CONTRACT["cli_commands"])
    assert REMOVED.isdisjoint(commands)


@pytest.mark.parametrize("command", sorted(REMOVED & {"advisor", "forge", "quickstart", "run", "tracelens", "wire"}))
def test_removed_cli_commands_are_unknown(command: str) -> None:
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output
    assert "deprecated" not in result.output.lower()


def test_mcp_tools_match_contract_exactly() -> None:
    names = _mcp_tool_names()
    assert names == set(CONTRACT["mcp_tools"])
    assert REMOVED.isdisjoint(names)


def test_sdk_exports_match_contract_exactly() -> None:
    assert set(ro.__all__) == set(CONTRACT["sdk_exports"])
    assert REMOVED.isdisjoint(ro.__all__)


def test_release_artifact_contract_is_explicit() -> None:
    assert CONTRACT["schema_version"] == 2
    assert CONTRACT["release_artifact"] == {
        "schema_version": 1,
        "cli_policy_option": "--policy",
        "mcp_policy_input": "policy_path",
        "fail_on": ["never", "fail", "hold-or-block-or-fail"],
    }
