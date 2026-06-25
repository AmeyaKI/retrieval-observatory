from __future__ import annotations

import random
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from retrieval_observatory.types import Document, StageSnapshot
from retrieval_observatory.tracing.types import RetrievalTrace


def _coerce_documents(items: Sequence[Any], corpus: Optional[Dict[str, str]] = None) -> List[Document]:
    """Normalize bare ids / (id, score) / dicts / Documents into ranked Documents.

    Lets callers pass the raw output of their retriever (usually a list of doc ids)
    straight into a stage without hand-building Document objects.
    """
    corpus = corpus or {}
    docs: List[Document] = []
    n = len(items)
    for rank, item in enumerate(items, start=1):
        if isinstance(item, Document):
            item.rank = rank
            docs.append(item)
        elif isinstance(item, dict):
            doc_id = str(item.get("id") or item.get("doc_id"))
            docs.append(Document(id=doc_id, text=item.get("text", corpus.get(doc_id, "")),
                                 score=float(item.get("score", n - rank + 1)), rank=rank))
        elif isinstance(item, (tuple, list)):
            doc_id = str(item[0])
            docs.append(Document(id=doc_id, text=corpus.get(doc_id, ""), score=float(item[1]), rank=rank))
        else:
            doc_id = str(item)
            docs.append(Document(id=doc_id, text=corpus.get(doc_id, ""), score=float(n - rank + 1), rank=rank))
    return docs


class _StageTimer:
    """Context manager that times a stage and records it on exit.

    Usage::

        with t.stage("bm25") as s:
            docs = run_bm25(q)
            s.results = docs          # bare ids are fine
    """

    def __init__(self, ctx: "_TraceContext", stage_id: str, corpus: Optional[Dict[str, str]], final: bool):
        self._ctx = ctx
        self._stage_id = stage_id
        self._corpus = corpus
        self._final = final
        self._start = 0.0
        self.results: Sequence[Any] = []

    def set_results(self, results: Sequence[Any]) -> None:
        self.results = results

    def __enter__(self) -> "_StageTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        latency_ms = (time.perf_counter() - self._start) * 1000
        docs = _coerce_documents(list(self.results), self._corpus)
        self._ctx.record_stage(self._stage_id, docs, latency_ms)
        if self._final and docs:
            self._ctx.set_results(docs)
        return False  # never suppress exceptions


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

    def stage(
        self,
        stage_id: str,
        documents: Optional[List[Document]] = None,
        latency_ms: Optional[float] = None,
        *,
        corpus: Optional[Dict[str, str]] = None,
        final: bool = False,
    ):
        """Record a stage, or open a timing context manager.

        Two forms:

        - Immediate: ``t.stage("bm25", docs, latency_ms)`` records right away.
        - Context manager (auto-timed): ``with t.stage("bm25") as s: s.results = ids``
          times the block and accepts bare doc ids (text resolved from ``corpus``).
        """
        if documents is None:
            return _StageTimer(self, stage_id, corpus, final)
        self.record_stage(stage_id, documents, latency_ms or 0.0)
        return None

    def record_stage(self, stage_id: str, documents: List[Document], latency_ms: float) -> None:
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

    def set_query_text(self, text: str) -> None:
        if not self._sampled:
            return
        self.trace.query_text = text


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

    def finish_trace_sync(
        self,
        ctx: _TraceContext,
        status: str = "OK",
        error: Optional[BaseException] = None,
    ) -> None:
        """Synchronous wrapper for finish_trace — for use in sync callback handlers.

        If an asyncio event loop is already running (e.g. inside an async server),
        the flush is scheduled as a fire-and-forget task; call
        ``await asyncio.sleep(0)`` after all chain.invoke() calls to ensure tasks
        complete before the loop exits.  If no loop is running (e.g. a sync script),
        asyncio.run() is used.
        """
        import asyncio

        coro = self.finish_trace(ctx, status=status, error=error)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    async def _flush(self, trace: RetrievalTrace) -> None:
        await self._sink.emit(trace)
