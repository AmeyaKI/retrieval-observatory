"""MCP integration ergonomics: describe_integration, verify_integration, config normalize."""
import os
from pathlib import Path

import pytest
import yaml

from retrieval_observatory.integrations.registry import describe_integration
from retrieval_observatory.mcp import server

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


@pytest.mark.asyncio
async def test_describe_integration_lists_frameworks():
    out = await server._describe_integration()
    assert "langchain" in out["frameworks"]
    assert "python" in out["guides"]


def test_describe_integration_snippets_use_real_apis():
    for fw in ("python", "langchain", "llamaindex", "fastapi"):
        guide = describe_integration(fw)
        snippet = guide["snippet"]
        assert "observe_run" not in snippet
        assert "observe_operator" not in snippet
        assert "push-traces" not in snippet
    lc = describe_integration("langchain")["snippet"]
    assert "RetobsLangChainCallbackV2" in lc
    li = describe_integration("llamaindex")["snippet"]
    assert "RetobsLlamaIndexCallbackV2" in li


def test_describe_integration_single_framework():
    guide = describe_integration("http")
    assert guide["framework"] == "http"
    assert "adapter.http" in guide["snippet"]


@pytest.mark.asyncio
async def test_verify_integration_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    out = await server._verify_integration(db_path=db)
    assert out["status"] == "no_runs"
    assert ":4000" in out["dashboard_url"]


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
    assert verify["instrumentation"] in ("benchmark_only", "trace_native")
    assert "bm25" in verify["pipeline_ids"]


@pytest.mark.asyncio
async def test_benchmark_config_file_relative_paths(tmp_path):
    queries_src = os.path.join(FIXTURES, "tiny_queries.jsonl")
    corpus_src = os.path.join(FIXTURES, "tiny_corpus.jsonl")
    config_dir = tmp_path / "project" / "retobs"
    config_dir.mkdir(parents=True)
    # copy fixtures with relative names
    (config_dir / "queries.jsonl").write_text(Path(queries_src).read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "corpus.jsonl").write_text(Path(corpus_src).read_text(encoding="utf-8"), encoding="utf-8")
    config = {
        "experiment": {"name": "file-bench"},
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": "queries.jsonl",
            "corpus_path": "corpus.jsonl",
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    db = str(tmp_path / "file.db")
    out = await server._benchmark_config_file(str(config_path), max_queries=3, db_path=db)
    assert out["run_id"]


@pytest.mark.asyncio
async def test_bootstrap_project_writes_files(tmp_path):
    root = tmp_path / "my-rag"
    out = await server._bootstrap_project(str(root), framework="python")
    assert (root / "retobs" / "config.yaml").exists()
    assert (root / "retobs-mcp.yaml").exists()
    assert (root / "retobs" / "retriever.py").exists()
    assert (root / ".retobs" / "manifest.yaml").exists()
    assert out.get("deprecated")


@pytest.mark.asyncio
async def test_push_traces_roundtrip(tmp_path):
    from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace

    db = str(tmp_path / "traces.db")
    descriptor = {
        "name": "trace-push",
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }
    bench = await server._benchmark_config(descriptor, max_queries=1, db_path=db)
    run_id = bench["run_id"]

    @observe("SOURCE", op_id="demo_source")
    def _source():
        return ["d1"]

    start_trace(ObserveContext(run_id=run_id, query_id="q1", query_text="cats", pipeline_id="bm25"))
    _source()
    trace = finish_trace()

    pushed = await server._push_traces(run_id, [trace.to_dict()], db_path=db)
    assert pushed["count"] == 1
    verify = await server._verify_integration(db_path=db, run_id=run_id)
    assert verify["trace_count"] >= 1
    assert verify["instrumentation"] == "trace_native"
    assert "demo_source" in verify["stages_seen"]


@pytest.mark.asyncio
async def test_build_server_includes_integration_tools():
    srv = server.build_server()
    tools = await srv.list_tools()
    names = {t.name for t in tools}
    assert "describe_integration" in names
    assert "verify_integration" in names
    assert "bootstrap_project" in names
    assert "wire_project" in names
    assert "push_traces" in names
    assert "benchmark_config_file" in names
    assert "get_pipeline_graph" in names

