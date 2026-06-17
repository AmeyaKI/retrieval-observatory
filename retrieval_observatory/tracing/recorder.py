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
        status = "ERROR" if exc is not None else "OK"
        error = exc if exc is not None else None
        await self._recorder.finish_trace(self._ctx, status=status, error=error, exc_type=exc_type, exc=exc, tb=tb)
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

    def start_trace(
        self,
        query_text: str,
        pipeline_id: str,
        query_id: str = "",
        metadata: Optional[dict] = None,
    ) -> _TraceContext:
        sampled = self.sample_rate >= 1.0 or random.random() < self.sample_rate
        return _TraceContext(self, query_text, pipeline_id, query_id, sampled, metadata or {})

    async def finish_trace(
        self,
        ctx: _TraceContext,
        status: str = "OK",
        error: Optional[BaseException] = None,
        *,
        exc_type=None,
        exc=None,
        tb=None,
    ) -> None:
        t = ctx.trace
        t.status = status  # type: ignore[assignment]
        if error is not None or exc is not None:
            t.status = "ERROR"
            if exc_type is not None and exc is not None and tb is not None:
                t.error_traceback = "".join(traceback.format_exception(exc_type, exc, tb))
            elif error is not None:
                t.error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if not t.final_results and t.snapshots:
            t.final_results = t.snapshots[-1].documents
        if ctx.sampled:
            await self._flush(t)

    def trace(self, query_text: str, pipeline_id: str, query_id: str = "", metadata: Optional[dict] = None) -> _TraceCM:
        ctx = self.start_trace(query_text, pipeline_id, query_id, metadata)
        return _TraceCM(self, ctx)

    async def _flush(self, trace: RetrievalTrace) -> None:
        await self._sink.emit(trace)
