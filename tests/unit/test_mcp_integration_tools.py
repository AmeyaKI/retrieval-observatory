"""MCP integration ergonomics: describe_integration, verify_integration, config normalize."""
import os

import pytest

from retrieval_observatory.integrations.registry import describe_integration
from retrieval_observatory.mcp import server

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


@pytest.mark.asyncio
async def test_describe_integration_lists_frameworks():
    out = await server._describe_integration()
    assert "langchain" in out["frameworks"]
    assert "python" in out["guides"]


def test_describe_integration_single_framework():
    guide = describe_integration("http")
    assert guide["framework"] == "http"
    assert "adapter.http" in guide["snippet"]


@pytest.mark.asyncio
async def test_verify_integration_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    out = await server._verify_integration(db_path=db)
    assert out["status"] == "no_runs"


@pytest.mark.asyncio
async def test_normalize_descriptor_shape(tmp_path):
    db = str(tmp_path / "norm.db")
    descriptor = {
        "name": "desc-test",
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }
    out = await server._benchmark_config(descriptor, max_queries=3, db_path=db)
    assert out["run_id"]
    verify = await server._verify_integration(db_path=db, run_id=out["run_id"])
    assert verify["status"] == "ok"
    assert "bm25" in verify["pipeline_ids"]


@pytest.mark.asyncio
async def test_build_server_includes_integration_tools():
    srv = server.build_server()
    tools = await srv.list_tools()
    names = {t.name for t in tools}
    assert "describe_integration" in names
    assert "verify_integration" in names
