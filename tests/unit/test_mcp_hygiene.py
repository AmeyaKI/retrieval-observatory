"""Input hygiene on the MCP/SDK seams: bad inputs fail with a named reason, not a KeyError."""
from __future__ import annotations

from pathlib import Path

import pytest

import retrieval_observatory as ro
from retrieval_observatory.mcp import server

_TRACE = {
    "trace_id": "t1", "service_id": "svc", "query_id": "q1", "query_text": "cats", "pipeline_id": "bm25",
    "spans": [], "final_op_ids": [], "timestamp": "2026-09-15T00:00:00+00:00",
}


async def test_push_traces_rejects_junk_with_field_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"trace\[0\] missing field 'trace_id'"):
        await server._push_traces("run-1", [{"foo": "bar"}], db_path=str(tmp_path / "t.db"))
    with pytest.raises(ValueError, match=r"trace\[1\] must be a JSON object"):
        await server._push_traces("run-1", [_TRACE, "nope"], db_path=str(tmp_path / "t.db"))


async def test_push_traces_requires_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id must be a non-empty string"):
        await server._push_traces("", [_TRACE], db_path=str(tmp_path / "t.db"))
    assert not (tmp_path / "t.db").exists()


async def test_evaluate_tool_requires_positive_max_queries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_queries must be at least 1"):
        await server._benchmark_config({"experiment": {"name": "x"}}, max_queries=0, db_path=str(tmp_path / "t.db"))


def test_sdk_evaluate_requires_positive_max_queries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_queries must be at least 1"):
        ro.evaluate(lambda q: [], queries=[{"query_id": "q1", "text": "cats"}], corpus={"d1": "cats"}, max_queries=0, db_path=str(tmp_path / "t.db"))
