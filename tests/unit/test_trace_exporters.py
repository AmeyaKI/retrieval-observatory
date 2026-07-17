import httpx
import pytest
from unittest.mock import AsyncMock, Mock

from retrieval_observatory.tracing.exporters import HTTPExporter, MemoryExporter, StoreExporter
from retrieval_observatory.tracing.serialization import NormalizationReport, NormalizedTrace

from tests.unit.test_trace_serialization import _trace


def _normalized_batch():
    return [NormalizedTrace(_trace().to_dict(), NormalizationReport())]


@pytest.mark.asyncio
async def test_store_exporter_writes_one_batch() -> None:
    store = Mock()
    store.save_traces = AsyncMock()
    await StoreExporter(store).export(_normalized_batch())
    store.save_traces.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_exporter_copies_batches() -> None:
    exporter = MemoryExporter()
    batch = _normalized_batch()
    await exporter.export(batch)
    batch.clear()
    assert len(exporter.batches[0]) == 1


@pytest.mark.asyncio
async def test_http_exporter_reuses_one_client() -> None:
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    exporter = HTTPExporter("http://retobs/api/production/traces", transport=httpx.MockTransport(handler))
    await exporter.export(_normalized_batch())
    await exporter.export(_normalized_batch())
    assert exporter.client_creation_count == 1
    assert len(requests) == 2
    await exporter.close()
