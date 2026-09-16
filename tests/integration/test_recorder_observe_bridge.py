"""A recorder-managed trace (instrument_fastapi, framework callbacks) must receive the spans of
``@observe`` functions called inside it, and release the decorator context when it finishes."""
from __future__ import annotations

import pytest

import retrieval_observatory as ro
from retrieval_observatory.sdk.observe import current_trace, observe
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.integrations.fastapi import instrument_fastapi

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@observe("SOURCE", op_id="lexical")
def lexical(query: str) -> list[dict]:
    return [{"id": "d1", "score": 1.0}, {"id": "d2", "score": 0.5}]


@observe("RERANK", op_id="rerank", parent_ids=("lexical",))
def rerank(query: str, hits: list[dict]) -> list[dict]:
    return hits[:1]


@pytest.mark.parametrize("handler_style", ["async", "sync"])
async def test_observe_spans_land_in_the_request_trace(tmp_path, handler_style: str) -> None:
    db = str(tmp_path / "bridge.db")
    recorder = ro.init("bridge-svc", db)
    app = fastapi.FastAPI()
    instrument_fastapi(app, recorder, pipeline_id="bridge-pipeline")

    if handler_style == "async":
        @app.get("/search")
        async def search(q: str):
            return rerank(q, lexical(q))
    else:
        @app.get("/search")
        def search(q: str):
            return rerank(q, lexical(q))

    with TestClient(app) as client:
        assert client.get("/search", params={"q": "cats"}).status_code == 200
    assert current_trace() is None

    store = SQLiteStore(db_path=db)
    await store.init_db()
    traces = await store.list_traces(TraceQuery(service_id="bridge-svc", pipeline_id="bridge-pipeline"))
    assert len(traces) == 1
    trace = traces[0]
    assert trace.query_text == "cats"
    assert [span.op_id for span in trace.spans] == ["lexical", "rerank"]
    assert [candidate.doc_id for candidate in trace.spans[0].outputs] == ["d1", "d2"]
    assert trace.spans[1].parent_ids == ("lexical",)
    assert trace.final_op_ids == ("rerank",)
    assert trace.timing is not None and trace.timing.wall_clock_ms > 0


def test_recorder_context_releases_previous_active_trace() -> None:
    from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
    from retrieval_observatory.tracing import BufferedTraceSink, MemoryExporter, TraceRecorder

    outer = start_trace(ObserveContext(None, "q1", "outer", "p", "svc"))
    recorder = TraceRecorder("svc", BufferedTraceSink(MemoryExporter(), service_id="svc"))
    context = recorder.start_trace("inner", "p")
    lexical("inner")
    assert [span.op_id for span in context.spans] == ["lexical"]
    assert outer.spans == ()
    recorder.finish(context)
    assert current_trace() is outer
    finish_trace()
