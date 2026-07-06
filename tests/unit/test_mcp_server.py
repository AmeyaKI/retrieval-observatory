"""P1.3 — MCP server tool registration + tool logic over a seeded db."""
import os

import pytest

from retrieval_observatory.mcp import server
from retrieval_observatory.sdk import run_from_config

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _seed(db_path: str) -> str:
    cfg = {
        "experiment": {"name": "mcp-test"},
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
        "output": {"store": "sqlite", "db_path": db_path},
    }
    return run_from_config(cfg, max_queries=5).run_id


@pytest.mark.asyncio
async def test_build_server_registers_tools():
    srv = server.build_server()
    tools = await srv.list_tools()
    names = {t.name for t in tools}
    assert {"list_runs", "benchmark_config", "benchmark_vs_baseline", "get_pipeline_diagram"} <= names


@pytest.mark.asyncio
async def test_mcp_read_tools(tmp_path):
    db_path = str(tmp_path / "mcp.db")
    run_id = _seed(db_path)

    runs = await server._list_runs(db_path=db_path)
    assert any(r["run_id"] == run_id for r in runs)

    metrics = await server._get_run_metrics(run_id, db_path=db_path)
    assert metrics

    diagram = await server._get_pipeline_diagram(run_id, db_path=db_path)
    assert diagram["pipelines"][0]["pipeline_id"] == "bm25"
    node = diagram["pipelines"][0]["nodes"][0]
    assert "recall" in node["metrics"]


@pytest.mark.asyncio
async def test_mcp_benchmark_config(tmp_path):
    db_path = str(tmp_path / "bench.db")
    cfg = {
        "experiment": {"name": "mcp-bench"},
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }
    out = await server._benchmark_config(cfg, max_queries=5, db_path=db_path)
    assert out["run_id"] and out["metrics"]


def test_mcp_loads_simple_config(tmp_path):
    config_path = tmp_path / "retobs-mcp.yaml"
    config_path.write_text("db_path: /tmp/results.db\nmax_queries: 12\n", encoding="utf-8")

    cfg = server.load_config(str(config_path))

    assert cfg["db_path"] == "/tmp/results.db"
    assert cfg["max_queries"] == 12


@pytest.mark.asyncio
async def test_mcp_benchmark_pipeline_descriptor(tmp_path):
    db_path = str(tmp_path / "descriptor.db")
    descriptor = {
        "name": "descriptor-test",
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }

    out = await server._benchmark_pipeline_descriptor(descriptor, max_queries=5, db_path=db_path)

    assert out["run_id"] and out["metrics"]
