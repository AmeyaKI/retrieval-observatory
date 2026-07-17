"""MCP registration and configuration contracts."""
import asyncio
import json
from pathlib import Path

from retrieval_observatory.mcp import server


ROOT = Path(__file__).resolve().parents[2]


def test_build_server_registers_only_the_public_contract() -> None:
    contract = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
    names = {tool.name for tool in asyncio.run(server.build_server().list_tools())}

    assert names == set(contract["mcp_tools"])


def test_mcp_loads_simple_config(tmp_path) -> None:
    config_path = tmp_path / "retobs-mcp.yaml"
    config_path.write_text("db_path: /tmp/results.db\nmax_queries: 12\n", encoding="utf-8")

    config = server.load_config(str(config_path))

    assert config["db_path"] == "/tmp/results.db"
    assert config["max_queries"] == 12
