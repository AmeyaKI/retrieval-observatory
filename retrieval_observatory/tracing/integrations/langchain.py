"""LangChain callback integration for TraceLens."""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from retrieval_observatory.tracing.recorder import TraceRecorder, TraceRecorderV2, _TraceContext, _TraceContextV2
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan
from retrieval_observatory.types import Document


# ---------------------------------------------------------------------------
# Legacy (V1) manual hook handler — kept for backward compatibility
# ---------------------------------------------------------------------------

class RetobsTraceHandler:
    """LangChain-compatible callback that emits retrieval stages to TraceRecorder.

    This is the manual hook-based API (legacy).  Callers invoke on_retriever_start /
    on_retriever_end / on_retriever_finish themselves.  For zero-touch integration,
    use RetobsLangChainCallback instead.

    .. deprecated:: Phase 5
        Prefer ``RetobsLangChainCallbackV2`` for new code.
    """

    def __init__(self, recorder: TraceRecorder, pipeline_id: str = "default"):
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        self._ctx: Optional[_TraceContext] = None

    def on_retriever_start(self, query: str, **kwargs: Any) -> None:
        self._ctx = self._recorder.start_trace(
            query_text=query,
            pipeline_id=self._pipeline_id,
            metadata=kwargs.get("metadata") or {},
        )

    def on_retriever_end(self, documents: List[Dict[str, Any]], latency_ms: float, stage_id: str = "retriever") -> None:
        if not self._ctx:
            return
        docs = [
            Document(id=str(d.get("id", i)), text=d.get("text", ""), score=float(d.get("score", 0)), rank=i + 1)
            for i, d in enumerate(documents)
        ]
        self._ctx.stage(stage_id, docs, latency_ms)

    async def on_retriever_finish(self) -> None:
        if self._ctx:
            if self._ctx.trace.snapshots:
                self._ctx.set_results(self._ctx.trace.snapshots[-1].documents)
            await self._recorder.finish_trace(self._ctx)
            self._ctx = None


def _lc_docs_to_retobs(documents: Sequence[Any]) -> List[Document]:
    """Convert LangChain Document objects to retobs Document objects."""
    result = []
    for i, doc in enumerate(documents):
        text = getattr(doc, "page_content", "") or ""
        metadata = getattr(doc, "metadata", {}) or {}
        doc_id = metadata.get("id") or metadata.get("doc_id") or str(i)
        score = float(metadata.get("score", 0) or metadata.get("relevance_score", 0) or 0)
        result.append(Document(id=str(doc_id), text=text, score=score, rank=i + 1))
    return result


def _lc_docs_to_candidates(documents: Sequence[Any], op_id: str) -> List[Candidate]:
    """Convert LangChain Document objects to V2 Candidate objects."""
    candidates: List[Candidate] = []
    for i, doc in enumerate(documents):
        text = getattr(doc, "page_content", "") or ""
        metadata = getattr(doc, "metadata", {}) or {}
        doc_id = metadata.get("id") or metadata.get("doc_id") or str(i)
        score = float(metadata.get("score", 0) or metadata.get("relevance_score", 0) or 0)
        candidates.append(Candidate(doc_id=str(doc_id), score=score, rank=i + 1, origin_op_ids=[op_id]))
    return candidates


try:
    from langchain_core.callbacks.base import BaseCallbackHandler

    _LC_AVAILABLE = True
except ImportError:
    BaseCallbackHandler = object  # type: ignore[misc,assignment]
    _LC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Legacy (V1) zero-touch callback — kept for backward compatibility
# ---------------------------------------------------------------------------

class RetobsLangChainCallback(BaseCallbackHandler):  # type: ignore[misc]
    """Real LangChain BaseCallbackHandler subclass for zero-touch trace emission.

    .. deprecated:: Phase 5
        Prefer ``RetobsLangChainCallbackV2`` for new code.  This class emits V1
        ``RetrievalTrace`` objects via ``TraceRecorder``.

    Usage::

        from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback
        cb = RetobsLangChainCallback(recorder)
        chain.invoke(query, config={"callbacks": [cb]})
    """

    def __init__(self, recorder: TraceRecorder, pipeline_id: str = "default"):
        if not _LC_AVAILABLE:
            raise ImportError(
                "RetobsLangChainCallback requires langchain-core. "
                "Install with: pip install retrieval-observatory[langchain]"
            )
        super().__init__()
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        self._traces: Dict[UUID, _TraceContext] = {}
        self._chain_start: Dict[UUID, float] = {}
        self._retriever_start: Dict[UUID, float] = {}
        self._root_of: Dict[UUID, UUID] = {}

    def on_chain_start(
        self,
        serialized: Optional[dict],
        inputs: dict,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        if parent_run_id is None:
            query_text = ""
            if isinstance(inputs, dict):
                for key in ("query", "question", "input", "human_input"):
                    if key in inputs:
                        query_text = str(inputs[key])
                        break
            elif isinstance(inputs, str):
                query_text = inputs
            ctx = self._recorder.start_trace(
                query_text=query_text,
                pipeline_id=self._pipeline_id,
                metadata=kwargs.get("metadata") or {},
            )
            self._traces[run_id] = ctx
            self._chain_start[run_id] = time.monotonic()
            self._root_of[run_id] = run_id
        else:
            root = self._root_of.get(parent_run_id)
            if root is not None:
                self._root_of[run_id] = root

    def on_chain_end(
        self,
        outputs: dict,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._traces.pop(run_id, None)
        if ctx is not None:
            if ctx.trace.snapshots:
                ctx.set_results(ctx.trace.snapshots[-1].documents)
            self._recorder.finish_trace_sync(ctx, status="OK")
            self._chain_start.pop(run_id, None)
            self._root_of.pop(run_id, None)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._traces.pop(run_id, None)
        if ctx is not None:
            self._recorder.finish_trace_sync(ctx, status="ERROR", error=error)
            self._chain_start.pop(run_id, None)
            self._root_of.pop(run_id, None)

    def on_retriever_start(
        self,
        serialized: dict,
        query: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._retriever_start[run_id] = time.monotonic()
        root = self._root_of.get(parent_run_id or run_id) or (parent_run_id and self._root_of.get(parent_run_id))
        if root and root in self._traces:
            ctx = self._traces[root]
            if not ctx.trace.query_text:
                ctx.set_query_text(query)
        if parent_run_id is not None:
            root_id = self._root_of.get(parent_run_id) or parent_run_id
            self._root_of[run_id] = root_id

    def on_retriever_end(
        self,
        documents: Sequence[Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        start = self._retriever_start.pop(run_id, None)
        latency_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0

        root = self._root_of.get(run_id) or (parent_run_id and self._root_of.get(parent_run_id))
        if root is None and parent_run_id is not None:
            root = parent_run_id
        ctx = self._traces.get(root) if root else None  # type: ignore[arg-type]
        if ctx is None:
            return

        docs = _lc_docs_to_retobs(documents)
        stage_id = f"retriever_{len(ctx.trace.snapshots)}" if ctx.trace.snapshots else "retriever"
        ctx.stage(stage_id, docs, latency_ms)

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._retriever_start.pop(run_id, None)

    # Async variants — delegate to sync so chain.ainvoke also works
    async def on_chain_start_async(self, serialized: dict, inputs: dict, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_chain_start(serialized, inputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_chain_end_async(self, outputs: dict, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_chain_end(outputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_chain_error_async(self, error: BaseException, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_chain_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_retriever_start_async(self, serialized: dict, query: str, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_retriever_start(serialized, query, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_retriever_end_async(self, documents: Sequence[Any], *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_retriever_end(documents, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_retriever_error_async(self, error: BaseException, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_retriever_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)


# ---------------------------------------------------------------------------
# V2 zero-touch callback — builds OperatorSpan / RetrievalTraceV2
# ---------------------------------------------------------------------------

class RetobsLangChainCallbackV2(BaseCallbackHandler):  # type: ignore[misc]
    """LangChain BaseCallbackHandler that emits V2 traces (OperatorSpan DAG).

    Usage::

        from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallbackV2
        cb = RetobsLangChainCallbackV2(recorder_v2)
        chain.invoke(query, config={"callbacks": [cb]})

    ``on_retriever_start/end`` produces a SOURCE span.
    """

    def __init__(self, recorder: TraceRecorderV2, pipeline_id: str = "default"):
        if not _LC_AVAILABLE:
            raise ImportError(
                "RetobsLangChainCallbackV2 requires langchain-core. "
                "Install with: pip install retrieval-observatory[langchain]"
            )
        super().__init__()
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        self._traces: Dict[UUID, _TraceContextV2] = {}
        self._chain_start: Dict[UUID, float] = {}
        self._retriever_start: Dict[UUID, float] = {}
        self._root_of: Dict[UUID, UUID] = {}

    def on_chain_start(
        self,
        serialized: Optional[dict],
        inputs: dict,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        if parent_run_id is None:
            query_text = ""
            if isinstance(inputs, dict):
                for key in ("query", "question", "input", "human_input"):
                    if key in inputs:
                        query_text = str(inputs[key])
                        break
            elif isinstance(inputs, str):
                query_text = inputs
            ctx = self._recorder.start_trace(
                query_text=query_text,
                pipeline_id=self._pipeline_id,
                metadata=kwargs.get("metadata") or {},
            )
            self._traces[run_id] = ctx
            self._chain_start[run_id] = time.monotonic()
            self._root_of[run_id] = run_id
        else:
            root = self._root_of.get(parent_run_id)
            if root is not None:
                self._root_of[run_id] = root

    def on_chain_end(
        self,
        outputs: dict,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._traces.pop(run_id, None)
        if ctx is not None:
            self._recorder.finish_trace_sync(ctx, status="OK")
            self._chain_start.pop(run_id, None)
            self._root_of.pop(run_id, None)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._traces.pop(run_id, None)
        if ctx is not None:
            self._recorder.finish_trace_sync(ctx, status="ERROR", error=error)
            self._chain_start.pop(run_id, None)
            self._root_of.pop(run_id, None)

    def on_retriever_start(
        self,
        serialized: dict,
        query: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._retriever_start[run_id] = time.monotonic()
        root = self._root_of.get(parent_run_id or run_id) or (parent_run_id and self._root_of.get(parent_run_id))
        if root and root in self._traces:
            ctx = self._traces[root]
            if not ctx.trace.query_text:
                ctx.set_query_text(query)
        if parent_run_id is not None:
            root_id = self._root_of.get(parent_run_id) or parent_run_id
            self._root_of[run_id] = root_id

    def on_retriever_end(
        self,
        documents: Sequence[Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        start = self._retriever_start.pop(run_id, None)
        latency_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0

        root = self._root_of.get(run_id) or (parent_run_id and self._root_of.get(parent_run_id))
        if root is None and parent_run_id is not None:
            root = parent_run_id
        ctx = self._traces.get(root) if root else None  # type: ignore[arg-type]
        if ctx is None:
            return

        op_id = f"source_{uuid.uuid4().hex[:8]}"
        candidates = _lc_docs_to_candidates(documents, op_id)
        span = OperatorSpan(
            op_id=op_id,
            op_type="SOURCE",
            op_name=f"retriever_{len(ctx.trace.spans)}" if ctx.trace.spans else "retriever",
            parent_ids=[ctx.trace.spans[-1].op_id] if ctx.trace.spans else [],
            status="FIRED",
            deterministic=False,
            replay_policy="NOT_REPLAYABLE",
            latency_ms=latency_ms,
            outputs=candidates,
        )
        ctx.add_span(span)

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._retriever_start.pop(run_id, None)

    # Async variants
    async def on_chain_start_async(self, serialized: dict, inputs: dict, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_chain_start(serialized, inputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_chain_end_async(self, outputs: dict, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_chain_end(outputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_chain_error_async(self, error: BaseException, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_chain_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_retriever_start_async(self, serialized: dict, query: str, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_retriever_start(serialized, query, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_retriever_end_async(self, documents: Sequence[Any], *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_retriever_end(documents, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    async def on_retriever_error_async(self, error: BaseException, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kwargs: Any) -> None:
        self.on_retriever_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)
