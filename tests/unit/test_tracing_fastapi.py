import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from retrieval_observatory.tracing import TraceRecorder, MemorySink
from retrieval_observatory.tracing.integrations.fastapi import get_trace, instrument_fastapi
from retrieval_observatory.tracing.sink import StoreSink
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document


@pytest.fixture
def app_with_tracing():
    sink = MemorySink()
    recorder = TraceRecorder(service="test-svc", sink=sink, sample_rate=1.0)
    app = FastAPI()
    instrument_fastapi(app, recorder, pipeline_id="bm25")

    @app.get("/ok")
    async def ok(request: Request):
        t = get_trace(request)
        assert t is not None
        t.stage("bm25", [Document("d1", "text", 0.9, 1)], 5.0)
        t.set_results([Document("d1", "text", 0.9, 1)])
        return {"hits": 1}

    @app.get("/fail")
    async def fail(request: Request):
        t = get_trace(request)
        if t:
            t.stage("bm25", [Document("d1", "text", 0.9, 1)], 5.0)
        raise RuntimeError("boom")

    return app, sink


def test_middleware_records_stages_on_success(app_with_tracing):
    app, sink = app_with_tracing
    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert len(sink.traces) == 1
    assert sink.traces[0].status == "OK"
    assert len(sink.traces[0].snapshots) == 1


def test_middleware_error_status_and_partial_stages(app_with_tracing):
    app, sink = app_with_tracing
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/fail")
    assert resp.status_code == 500
    assert len(sink.traces) == 1
    assert sink.traces[0].status == "ERROR"
    assert len(sink.traces[0].snapshots) == 1


def test_sample_rate_zero_records_nothing():
    sink = MemorySink()
    recorder = TraceRecorder(service="test-svc", sink=sink, sample_rate=0.0)
    app = FastAPI()
    instrument_fastapi(app, recorder)

    @app.get("/x")
    async def x():
        return {}

    client = TestClient(app)
    client.get("/x")
    assert len(sink.traces) == 0


@pytest.mark.asyncio
async def test_store_sink_persists_traces_from_recorder(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "traces.db"))
    await store.init_db()
    sink = StoreSink(store)
    recorder = TraceRecorder(service="api-svc", sink=sink, sample_rate=1.0)

    async with recorder.trace(query_text="store sink query", pipeline_id="bm25") as t:
        t.stage("bm25", [Document("d1", "text", 0.9, 1)], 8.0)
        t.set_results([Document("d1", "text", 0.9, 1)])

    rows = await store.list_traces("api-svc")
    assert len(rows) == 1
    assert rows[0]["query_text"] == "store sink query"
