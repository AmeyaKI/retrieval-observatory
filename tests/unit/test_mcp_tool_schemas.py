"""Every MCP tool must publish its real named parameters so an agent can call it by name."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from retrieval_observatory.mcp import server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import materialize  # noqa: E402

pytest.importorskip("mcp")


def _text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return next(block.text for block in content if getattr(block, "type", "") == "text")


async def test_tool_schemas_expose_named_parameters() -> None:
    tools = {tool.name: tool for tool in await server.build_server().list_tools()}
    for tool in tools.values():
        properties = tool.inputSchema.get("properties", {})
        assert "args" not in properties and "kwargs" not in properties, tool.name
    assert {"project_root", "phase", "plan", "plan_path", "db_path", "framework"} <= set(tools["integrate_project"].inputSchema["properties"])
    assert tools["integrate_project"].inputSchema["required"] == ["project_root"]
    evaluate = tools["evaluate"].inputSchema["properties"]
    assert evaluate["max_queries"]["default"] == server.DEFAULT_MAX_QUERIES
    assert evaluate["db_path"]["default"] == server.DEFAULT_DB_PATH
    assert {"run_id", "traces"} <= set(tools["push_traces"].inputSchema["properties"])


async def test_config_defaults_are_substituted_into_the_schema(tmp_path: Path) -> None:
    config = tmp_path / "retobs-mcp.yaml"
    config.write_text(f"db_path: {tmp_path / 'custom.db'}\nmax_queries: 7\n", encoding="utf-8")
    tools = {tool.name: tool for tool in await server.build_server(str(config)).list_tools()}
    assert tools["evaluate"].inputSchema["properties"]["max_queries"]["default"] == 7
    assert tools["get_report"].inputSchema["properties"]["db_path"]["default"] == str(tmp_path / "custom.db")


async def test_integrate_project_is_callable_through_the_server(tmp_path: Path) -> None:
    root = materialize("proj_a", tmp_path)
    result = await server.build_server().call_tool("integrate_project", {"project_root": str(root), "phase": "plan"})
    payload = json.loads(_text(result))
    assert payload["status"] == "planned"
    assert [op["symbol"] for op in payload["plan"]["operators"]] == ["retrieve"]
