from __future__ import annotations

import random
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from retrieval_observatory.types import Document, StageSnapshot
from retrieval_observatory.tracing.candidates import build_candidate_transition, to_candidates
from retrieval_observatory.tracing.types import RetrievalTrace
from retrieval_observatory.tracing.model_v2 import (
    Candidate,
    OperatorSpan,
    RetrievalTraceV2,
    TraceTiming,
    critical_path_latency_ms,
)


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


# Legacy alias so ``from recorder import LegacyTraceRecorder`` keeps working.
LegacyTraceRecorder = TraceRecorder


# ---------------------------------------------------------------------------
# V2 recorder — builds OperatorSpan / RetrievalTraceV2 objects
# ---------------------------------------------------------------------------

def _docs_to_candidates(items: Sequence[Any], op_id: str) -> List[Candidate]:
    """Normalize bare ids / Document objects / dicts into Candidate list."""
    if all(isinstance(item, Candidate) for item in items):
        return list(items)  # type: ignore[return-value]
    return to_candidates(list(items), op_id)


class _TraceContextV2:
    """Handle yielded inside a ``TraceRecorderV2.trace(...)`` block."""

    def __init__(
        self,
        recorder: "TraceRecorderV2",
        query_text: str,
        pipeline_id: str,
        query_id: str,
        sampled: bool,
        metadata: dict,
        request_id: Optional[str],
    ):
        self._recorder = recorder
        self._sampled = sampled
        self._started = time.perf_counter()
        self.trace = RetrievalTraceV2(
            trace_id=uuid.uuid4().hex,
            run_id=recorder.service,
            query_id=query_id or uuid.uuid4().hex,
            query_text=query_text,
            pipeline_id=pipeline_id,
            spans=[],
            total_latency_ms=0.0,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {},
            request_id=request_id,
        )

    @property
    def sampled(self) -> bool:
        return self._sampled

    def add_span(self, span: OperatorSpan) -> None:
        if not self._sampled:
            return
        self.trace.spans.append(span)

    def span(
        self,
        op_type: str,
        op_name: str,
        documents: Sequence[Any],
        latency_ms: float,
        *,
        op_id: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        deterministic: bool = False,
        replay_policy: str = "NOT_REPLAYABLE",
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[OperatorSpan]:
        """Convenience: build an OperatorSpan from raw documents and append it."""
        if not self._sampled:
            return None
        resolved_id = op_id or f"{op_type.lower()}_{uuid.uuid4().hex[:8]}"
        resolved_parents = parent_ids or ([self.trace.spans[-1].op_id] if self.trace.spans else [])
        spans_by_id = {span.op_id: span for span in self.trace.spans}
        input_groups = {
            parent_id: spans_by_id[parent_id].outputs
            for parent_id in resolved_parents
            if parent_id in spans_by_id
        }
        inputs, outputs = build_candidate_transition(
            input_groups=input_groups,
            output_items=documents,
            op_id=resolved_id,
            op_type=op_type,
        )
        span = OperatorSpan(
            op_id=resolved_id,
            op_type=op_type,  # type: ignore[arg-type]
            op_name=op_name,
            parent_ids=resolved_parents,
            status="FIRED",
            deterministic=deterministic,
            replay_policy=replay_policy,  # type: ignore[arg-type]
            latency_ms=latency_ms,
            inputs=inputs,
            outputs=outputs,
            params=params or {},
        )
        self.add_span(span)
        return span

    def set_query_text(self, text: str) -> None:
        if self._sampled:
            self.trace.query_text = text


class _TraceCMV2:
    def __init__(self, recorder: "TraceRecorderV2", ctx: _TraceContextV2):
        self._recorder = recorder
        self._ctx = ctx

    async def __aenter__(self) -> _TraceContextV2:
        return self._ctx

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        status = "ERROR" if exc is not None else "OK"
        error = exc if exc is not None else None
        await self._recorder.finish_trace(self._ctx, status=status, error=error, exc_type=exc_type, exc=exc, tb=tb)
        return False


class TraceRecorderV2:
    """V2 recorder that emits OperatorSpan / RetrievalTraceV2 traces.

    Drop-in replacement for TraceRecorder with the same ``trace()`` context
    manager pattern, but builds V2 data structures internally.
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
        request_id: Optional[str] = None,
    ) -> _TraceContextV2:
        sampled = self.sample_rate >= 1.0 or random.random() < self.sample_rate
        return _TraceContextV2(self, query_text, pipeline_id, query_id, sampled, metadata or {}, request_id)

    async def finish_trace(
        self,
        ctx: _TraceContextV2,
        status: str = "OK",
        error: Optional[BaseException] = None,
        *,
        exc_type=None,
        exc=None,
        tb=None,
    ) -> RetrievalTraceV2:
        t = ctx.trace
        t.status = status  # type: ignore[assignment]
        if error is not None or exc is not None:
            t.status = "ERROR"
            if exc_type is not None and exc is not None and tb is not None:
                t.error_traceback = "".join(traceback.format_exception(exc_type, exc, tb))
            elif error is not None:
                t.error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        operator_sum_ms = sum(max(0.0, span.latency_ms) for span in t.spans)
        wall_clock_ms = (time.perf_counter() - ctx._started) * 1000
        t.total_latency_ms = wall_clock_ms
        t.timing = TraceTiming(
            wall_clock_ms=wall_clock_ms,
            critical_path_ms=critical_path_latency_ms(t.spans),
            operator_sum_ms=operator_sum_ms,
        )
        if t.final_op_id is None and t.spans:
            parent_ids = {parent for span in t.spans for parent in span.parent_ids}
            sinks = [span.op_id for span in t.spans if span.op_id not in parent_ids]
            t.final_op_id = sinks[0] if len(sinks) == 1 else None
        if ctx.sampled:
            await self._flush(t)
        return t

    def trace(
        self,
        query_text: str,
        pipeline_id: str,
        query_id: str = "",
        metadata: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> _TraceCMV2:
        ctx = self.start_trace(query_text, pipeline_id, query_id, metadata, request_id)
        return _TraceCMV2(self, ctx)

    def finish_trace_sync(
        self,
        ctx: _TraceContextV2,
        status: str = "OK",
        error: Optional[BaseException] = None,
    ) -> None:
        import asyncio

        coro = self.finish_trace(ctx, status=status, error=error)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    async def _flush(self, trace: RetrievalTraceV2) -> None:
        if hasattr(self._sink, "emit_v2"):
            await self._sink.emit_v2(trace)
        else:
            await self._sink.emit(trace)
