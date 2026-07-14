"""MCP wire_project tool."""
import pytest

from retrieval_observatory.mcp import server
from retrieval_observatory.integrations.wire import plan_project


def test_plan_project_is_read_only_and_explicit(tmp_path):
    (tmp_path / "app.py").write_text("def retrieve(q): return []\n", encoding="utf-8")
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    out = plan_project(tmp_path)
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert out["status"] == "planned"
    assert out["files_written"] == []
    assert out["verification_criteria"]
    assert out["support"]["level"] == "first_class"
    assert before == after


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
    assert out["status"] == "not_verified"
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
    assert "plan_integration" in names
