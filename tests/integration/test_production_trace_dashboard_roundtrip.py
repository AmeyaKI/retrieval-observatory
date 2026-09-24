from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.config import TelemetryConfig
from retrieval_observatory.tracing.exporters import StoreExporter
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace
from retrieval_observatory.tracing.sink import BufferedTraceSink, FlushResult


def _trace(trace_id: str = "production-1") -> RetrievalTrace:
    return RetrievalTrace(
        trace_id=trace_id,
        service_id="search",
        run_id=None,
        query_id="q1",
        query_text="query",
        pipeline_id="hybrid",
        spans=(OperatorSpan.source("source", "Source", ()),),
        final_op_ids=("source",),
        timestamp=datetime.now(timezone.utc),
    )


def _listed(client: TestClient) -> list[str]:
    response = client.get("/production/traces", params={"service_id": "search"})
    assert response.status_code == 200, response.text
    return [item["trace_id"] for item in response.json()["items"]]


def test_production_trace_is_visible_without_run(tmp_path) -> None:
    path = tmp_path / "production.db"
    trace = _trace()
    client = TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))
    assert client.post("/production/traces", json=trace.to_dict()).json() == {"ingested": 1}
    services = client.get("/production/services").json()
    traces = client.get("/production/traces", params={"service_id": "search"}).json()
    assert services[0]["service_id"] == "search"
    assert traces["items"][0]["trace_id"] == "production-1"
    assert traces["items"][0]["run_id"] is None


def test_buffered_sink_trace_is_evidence_only_after_flush(tmp_path) -> None:
    path = tmp_path / "production.db"
    client = TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))

    async def scenario() -> tuple[list[str], FlushResult, list[str]]:
        store = SQLiteStore(str(path))
        await store.init_db()
        sink = BufferedTraceSink(StoreExporter(store), service_id="search")
        assert sink.offer(_trace("buffered-1"))
        before = _listed(client)  # offered, not yet exported: the worker has not started
        await sink.start()
        flushed = await sink.flush(timeout_s=5)
        after = _listed(client)
        await sink.shutdown(timeout_s=1)
        return before, flushed, after

    before, flushed, after = asyncio.run(scenario())
    assert before == []
    assert flushed == FlushResult(timed_out=False, unflushed=0)
    assert after == ["buffered-1"]


def test_flush_against_blocked_exporter_reports_unflushed_traces(tmp_path) -> None:
    path = tmp_path / "production.db"
    client = TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))

    class BlockedStoreExporter(StoreExporter):
        def __init__(self, store: SQLiteStore) -> None:
            super().__init__(store)
            self.release = asyncio.Event()

        async def export(self, batch) -> None:
            await self.release.wait()
            await super().export(batch)

    async def scenario() -> tuple[FlushResult, list[str], int]:
        store = SQLiteStore(str(path))
        await store.init_db()
        exporter = BlockedStoreExporter(store)
        sink = BufferedTraceSink(exporter, TelemetryConfig(export_timeout_s=5, max_retries=0), service_id="search")
        await sink.start()
        assert sink.offer(_trace("blocked-1"))
        flushed = await sink.flush(timeout_s=0.05)
        listed = _listed(client)
        exporter.release.set()
        await sink.shutdown(timeout_s=1)
        return flushed, listed, sink.health().exported

    flushed, listed, exported = asyncio.run(scenario())
    assert flushed.timed_out is True and flushed.unflushed == 1
    assert listed == []  # a timed-out flush is not persisted evidence
    assert exported == 1  # released before shutdown: the drain completes the export


def test_flush_reports_traces_whose_export_failed_permanently(tmp_path) -> None:
    path = tmp_path / "production.db"
    client = TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))

    class FailingStoreExporter(StoreExporter):
        async def export(self, batch) -> None:
            raise ConnectionError("store unavailable")

    async def scenario() -> tuple[FlushResult, FlushResult, list[str]]:
        store = SQLiteStore(str(path))
        await store.init_db()
        sink = BufferedTraceSink(FailingStoreExporter(store), TelemetryConfig(max_retries=1, retry_base_s=0), service_id="search")
        await sink.start()
        assert sink.offer(_trace("failed-1")) and sink.offer(_trace("failed-2"))
        flushed = await sink.flush(timeout_s=5)
        again = await sink.flush(timeout_s=1)  # nothing failed in this window
        listed = _listed(client)
        await sink.shutdown(timeout_s=1)
        return flushed, again, listed

    flushed, again, listed = asyncio.run(scenario())
    assert flushed == FlushResult(timed_out=False, unflushed=0, failed=2)
    assert again == FlushResult(timed_out=False, unflushed=0, failed=0)
    assert listed == []
