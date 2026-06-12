from __future__ import annotations

import random
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from retrieval_observatory.types import Document, StageSnapshot
from retrieval_observatory.tracing.types import RetrievalTrace


class _TraceContext:
    """The handle yielded inside a ``recorder.trace(...)`` block."""

    def __init__(self, recorder: "TraceRecorder", query_text: str, pipeline_id: str, query_id: str, sampled: bool, metadata: dict):
        self._recorder = recorder
        self._sampled = sampled
        self.trace = RetrievalTrace(
            trace_id=uuid.uuid4().hex,
            service=recorder.service,
            query_id=query_id or uuid.uuid4().hex,
            query_text=query_text,
            pipeline_id=pipeline_id,
            snapshots=[],
            total_latency_ms=0.0,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

    @property
    def sampled(self) -> bool:
        return self._sampled

    def stage(self, stage_id: str, documents: List[Document], latency_ms: float) -> None:
        if not self._sampled:
            return
        idx = len(self.trace.snapshots)
        self.trace.snapshots.append(
            StageSnapshot(
                stage_index=idx,
                stage_id=stage_id,
                documents=list(documents),
                latency_ms=latency_ms,
                candidate_count=len(documents),
            )
        )
        self.trace.total_latency_ms += latency_ms

    def set_results(self, documents: List[Document]) -> None:
        if not self._sampled:
            return
        self.trace.final_results = list(documents)


class _TraceCM:
    def __init__(self, recorder: "TraceRecorder", ctx: _TraceContext):
        self._recorder = recorder
        self._ctx = ctx

    async def __aenter__(self) -> _TraceContext:
        return self._ctx

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        t = self._ctx.trace
        if exc is not None:
            t.status = "ERROR"
            t.error_traceback = "".join(traceback.format_exception(exc_type, exc, tb))
        if not t.final_results and t.snapshots:
            t.final_results = t.snapshots[-1].documents
        if self._ctx.sampled:
            await self._recorder._flush(t)
        return False  # never suppress the exception


class TraceRecorder:
    """Lightweight SDK for emitting production retrieval traces.

    Usage::

        recorder = TraceRecorder(service="prod-search", sink=StoreSink(store))
        async with recorder.trace(query_text=q, pipeline_id="hybrid") as t:
            docs = bm25.retrieve(q)
            t.stage("bm25", docs.documents, docs.latency_ms)
            t.set_results(docs.documents)
    """

    def __init__(self, service: str, sink: Any, sample_rate: float = 1.0):
        self.service = service
        self._sink = sink
        self.sample_rate = max(0.0, min(1.0, sample_rate))

    def trace(self, query_text: str, pipeline_id: str, query_id: str = "", metadata: Optional[dict] = None) -> _TraceCM:
        sampled = self.sample_rate >= 1.0 or random.random() < self.sample_rate
        ctx = _TraceContext(self, query_text, pipeline_id, query_id, sampled, metadata or {})
        return _TraceCM(self, ctx)

    async def _flush(self, trace: RetrievalTrace) -> None:
        await self._sink.emit(trace)
