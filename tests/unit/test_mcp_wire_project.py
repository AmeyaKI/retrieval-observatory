"""MCP wire_project tool."""
import pytest

from retrieval_observatory.mcp import server


@pytest.mark.asyncio
async def test_wire_project_setup(tmp_path):
    (tmp_path / "search.py").write_text("def retrieve(q): return []\n", encoding="utf-8")
    out = await server._wire_project(str(tmp_path), phase="setup")
    assert out["status"] == "setup_complete"
    assert "wiring_brief" in out
    assert "post_wiring_commands" in out


@pytest.mark.asyncio
async def test_wire_project_verify(tmp_path):
    await server._wire_project(str(tmp_path), phase="setup")
    out = await server._wire_project(str(tmp_path), phase="verify")
    assert out["status"] == "ready"
    assert "commands" in out


@pytest.mark.asyncio
async def test_bootstrap_project_backward_compat(tmp_path):
    out = await server._bootstrap_project(str(tmp_path))
    assert out.get("deprecated")
    assert out["status"] == "setup_complete"


@pytest.mark.asyncio
async def test_build_server_includes_wire_project():
    srv = server.build_server()
    tools = await srv.list_tools()
    names = {t.name for t in tools}
    assert "wire_project" in names
