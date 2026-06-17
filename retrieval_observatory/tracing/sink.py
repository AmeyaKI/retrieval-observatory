from __future__ import annotations

import json
from typing import Any, List, Protocol, runtime_checkable

from retrieval_observatory.tracing.types import RetrievalTrace


def trace_to_dict(t: RetrievalTrace) -> dict:
    """Serialize a trace to a JSON-ready dict (matches the ingestion API schema)."""
    def doc_to_dict(d: Any) -> dict:
        return {
            "id": d.id,
            "text": getattr(d, "text", ""),
            "score": d.score,
            "rank": d.rank,
            "title": getattr(d, "title", ""),
        }

    return {
        "trace_id": t.trace_id,
        "service": t.service,
        "query_id": t.query_id,
        "query_text": t.query_text,
        "pipeline_id": t.pipeline_id,
        "status": t.status,
        "total_latency_ms": t.total_latency_ms,
        "timestamp": t.timestamp.isoformat(),
        "metadata": t.metadata,
        "snapshots": [
            {
                "stage_index": s.stage_index,
                "stage_id": s.stage_id,
                "latency_ms": s.latency_ms,
                "candidate_count": s.candidate_count or len(s.documents),
                "documents": [doc_to_dict(d) for d in s.documents],
            }
            for s in t.snapshots
        ],
        "final_results": [doc_to_dict(d) for d in t.final_results],
    }


@runtime_checkable
class TraceSink(Protocol):
    async def emit(self, trace: RetrievalTrace) -> None:
        ...


class StoreSink:
    """Writes traces straight to a BaseStore (for services colocated with the store)."""

    def __init__(self, store: Any, latency_budget_ms: float = 2000.0):
        self._store = store
        self._latency_budget_ms = latency_budget_ms

    async def emit(self, trace: RetrievalTrace) -> None:
        from retrieval_observatory.tracing.enrich import enrich

        enrich(trace, latency_budget_ms=self._latency_budget_ms)
        await self._store.save_trace(trace)


class HTTPSink:
    """POSTs traces to a TraceLens ingestion endpoint (for remote services)."""

    def __init__(self, endpoint: str, timeout: float = 5.0):
        # endpoint e.g. "http://observatory:8000/tracelens/traces"
        self._endpoint = endpoint
        self._timeout = timeout

    async def emit(self, trace: RetrievalTrace) -> None:
        import httpx

        payload = trace_to_dict(trace)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            await client.post(self._endpoint, json=payload)


class MemorySink:
    """Collects traces in memory — used by tests and the CLI demo seeder."""

    def __init__(self) -> None:
        self.traces: List[RetrievalTrace] = []

    async def emit(self, trace: RetrievalTrace) -> None:
        self.traces.append(trace)
