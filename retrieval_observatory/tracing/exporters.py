import asyncio
from typing import Protocol, Sequence

import httpx

from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.tracing.serialization import NormalizedTrace


class TraceExporter(Protocol):
    async def export(self, batch: Sequence[NormalizedTrace]) -> None: ...
    async def close(self) -> None: ...


class StoreExporter:
    def __init__(self, store) -> None:
        self.store = store

    async def export(self, batch: Sequence[NormalizedTrace]) -> None:
        await self.store.save_traces([RetrievalTrace.from_dict(item.payload) for item in batch])

    async def close(self) -> None:
        return None


class MemoryExporter:
    def __init__(self) -> None:
        self.batches: list[list[NormalizedTrace]] = []
        self._lock = asyncio.Lock()

    async def export(self, batch: Sequence[NormalizedTrace]) -> None:
        async with self._lock:
            self.batches.append(list(batch))

    async def close(self) -> None:
        return None


class HTTPExporter:
    def __init__(
        self,
        endpoint: str,
        *,
        timeout_s: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport, headers=headers)
        self.client_creation_count = 1
        self._closed = False

    async def export(self, batch: Sequence[NormalizedTrace]) -> None:
        if self._closed:
            raise RuntimeError("exporter is closed")
        response = await self._client.post(
            self._endpoint,
            json={"traces": [item.payload for item in batch]},
        )
        response.raise_for_status()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()
