"""``trace_scope`` turns one entrypoint call into a persisted trace, and steps aside when a
trace is already active."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from retrieval_observatory.sdk.observe import ObserveContext, current_trace, finish_trace, observe, start_trace, trace_scope
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore


@observe("SOURCE", op_id="source")
def source(query: str) -> list[dict]:
    return [{"id": "d1", "score": 1.0}]


async def _traces(db: str):
    store = SQLiteStore(db_path=db)
    await store.init_db()
    return await store.list_traces(TraceQuery(service_id="svc", pipeline_id="pipe"))


def _stored(db: str):
    return asyncio.run(_traces(db))


def test_sync_entrypoint_persists_a_trace(tmp_path: Path) -> None:
    db = str(tmp_path / "scope.db")

    @trace_scope("svc", "pipe", db_path=db)
    def retrieve(query: str, k: int = 3):
        return source(query)[:k]

    assert retrieve("lexical sparse", k=1) == [{"id": "d1", "score": 1.0}]
    assert current_trace() is None
    traces = _stored(db)
    assert len(traces) == 1
    trace = traces[0]
    assert trace.query_text == "lexical sparse"
    assert [span.op_id for span in trace.spans] == ["source"]
    assert trace.spans[0].outputs[0].doc_id == "d1"
    assert trace.status == "OK" and trace.timing is not None and trace.timing.wall_clock_ms > 0


async def test_async_entrypoint_persists_before_returning(tmp_path: Path) -> None:
    db = str(tmp_path / "scope.db")

    @trace_scope("svc", "pipe", db_path=db)
    async def retrieve(question: str):
        return source(question)

    await retrieve("async question")
    assert (await _traces(db))[0].query_text == "async question"


def test_noop_when_a_trace_is_already_active(tmp_path: Path) -> None:
    db = tmp_path / "scope.db"

    @trace_scope("svc", "pipe", db_path=str(db))
    def retrieve(query: str):
        return source(query)

    start_trace(ObserveContext(None, "q1", "outer", "pipe", "svc"))
    retrieve("inner")
    trace = finish_trace()
    assert [span.op_id for span in trace.spans] == ["source"]
    assert not db.exists()


async def test_sync_entrypoint_inside_a_running_loop_schedules_persistence(tmp_path: Path) -> None:
    from retrieval_observatory.sdk.observe import _pending_persists

    db = str(tmp_path / "scope.db")

    @trace_scope("svc", "pipe", db_path=db)
    def retrieve(query: str):
        return source(query)

    retrieve("scheduled")
    await asyncio.gather(*_pending_persists)
    assert (await _traces(db))[0].query_text == "scheduled"


def test_error_is_recorded_and_reraised(tmp_path: Path) -> None:
    db = str(tmp_path / "scope.db")

    @trace_scope("svc", "pipe", db_path=db)
    def retrieve(query: str):
        raise RuntimeError("index unavailable")

    with pytest.raises(RuntimeError, match="index unavailable"):
        retrieve("boom")
    trace = _stored(db)[0]
    assert trace.status == "ERROR"
    assert "index unavailable" in (trace.error_traceback or "")


def test_query_text_from_request_body_attribute_and_method_self(tmp_path: Path) -> None:
    db = str(tmp_path / "scope.db")

    class Searcher:
        @trace_scope("svc", "pipe", db_path=db)
        def search(self, body):
            return source(body.q)

    Searcher().search(SimpleNamespace(q="from body", k=2))
    assert _stored(db)[0].query_text == "from body"


def test_relative_db_path_is_anchored_at_the_manifest_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    (root / "retobs").mkdir(parents=True)
    (root / "retobs" / "integration.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    module_path = root / "pkg_module.py"
    module_path.write_text(
        "from retrieval_observatory.sdk.observe import observe, trace_scope\n"
        '@trace_scope("svc", "pipe", db_path=".retobs/results.db")\n'
        '@observe("SOURCE", op_id="source", parent_ids=())\n'
        "def retrieve(query):\n"
        "    return [{'id': 'd1', 'score': 1.0}]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)  # not the project root: the manifest, not the cwd, anchors the path
    spec = importlib.util.spec_from_file_location("pkg_module_scope_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.retrieve("anchored")
    assert (root / ".retobs" / "results.db").is_file()
    assert _stored(str(root / ".retobs" / "results.db"))[0].query_text == "anchored"
