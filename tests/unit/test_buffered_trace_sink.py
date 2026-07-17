from datetime import datetime, timezone
import asyncio
import time

import pytest

from retrieval_observatory.tracing.config import OverflowPolicy, TelemetryConfig
from retrieval_observatory.tracing.exporters import MemoryExporter
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace
from retrieval_observatory.tracing.sink import BufferedTraceSink


def _trace(trace_id: str) -> RetrievalTrace:
    return RetrievalTrace(
        trace_id,
        "svc",
        None,
        "q",
        "query",
        "pipe",
        (OperatorSpan.source("source", "source", ()),),
        ("source",),
        datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_sink_is_bounded_and_exports_without_awaiting_offer() -> None:
    exporter = MemoryExporter()
    sink = BufferedTraceSink(exporter, TelemetryConfig(queue_capacity=1, batch_size=1), service_id="svc")
    assert sink.offer(_trace("one"))
    assert not sink.offer(_trace("two"))
    await sink.start()
    assert not (await sink.shutdown(1)).timed_out
    assert sink.health().dropped == 1
    assert len(exporter.batches) == 1


class _HangingExporter:
    async def export(self, batch) -> None:
        await asyncio.Event().wait()

    async def close(self) -> None:
        return None


class _FlakyExporter(MemoryExporter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def export(self, batch) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary")
        await super().export(batch)


@pytest.mark.asyncio
async def test_drop_newest_offer_never_blocks() -> None:
    sink = BufferedTraceSink(_HangingExporter(), TelemetryConfig(queue_capacity=1, batch_size=1))
    await sink.start()
    assert sink.offer(_trace("one")) is True
    started = time.perf_counter()
    assert sink.offer(_trace("two")) is False
    assert time.perf_counter() - started < 0.01
    assert sink.health().drop_reasons == {"queue_full": 1}
    await sink.shutdown(0)


@pytest.mark.asyncio
async def test_drop_oldest_accepts_replacement() -> None:
    sink = BufferedTraceSink(
        MemoryExporter(),
        TelemetryConfig(queue_capacity=1, batch_size=1, overflow_policy=OverflowPolicy.DROP_OLDEST),
    )
    assert sink.offer(_trace("one")) is True
    assert sink.offer(_trace("two")) is True
    assert sink.health().drop_reasons == {"queue_full_oldest": 1}
    await sink.start()
    await sink.shutdown(1)


@pytest.mark.asyncio
async def test_retry_then_success() -> None:
    exporter = _FlakyExporter()
    sink = BufferedTraceSink(
        exporter,
        TelemetryConfig(max_retries=1, retry_base_s=0, export_timeout_s=1),
    )
    await sink.start()
    sink.offer(_trace("one"))
    result = await sink.shutdown(1)
    assert result.timed_out is False
    assert exporter.calls == 2
    assert sink.health().retries == 1
    assert sink.health().exported == 1


@pytest.mark.asyncio
async def test_shutdown_honors_deadline() -> None:
    sink = BufferedTraceSink(
        _HangingExporter(),
        TelemetryConfig(shutdown_timeout_s=0.05, export_timeout_s=10),
    )
    await sink.start()
    sink.offer(_trace("one"))
    await asyncio.sleep(0)
    started = time.perf_counter()
    result = await sink.shutdown(0.05)
    assert result.timed_out is True
    assert result.unflushed >= 1
    assert time.perf_counter() - started < 0.15
