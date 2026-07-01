"""LlamaIndex callback integration for TraceLens."""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from retrieval_observatory.tracing.recorder import TraceRecorder, TraceRecorderV2, _TraceContext, _TraceContextV2
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan
from retrieval_observatory.types import Document


# ---------------------------------------------------------------------------
# Legacy (V1) manual hook handler — kept for backward compatibility
# ---------------------------------------------------------------------------

class RetobsLlamaIndexHandler:
    """Hook wrapper for LlamaIndex retrieval events → TraceRecorder.

    .. deprecated:: Phase 5
        Prefer ``RetobsLlamaIndexCallbackV2`` for new code.
    """

    def __init__(self, recorder: TraceRecorder, pipeline_id: str = "default"):
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        self._ctx: Optional[_TraceContext] = None

    def on_retrieve_start(self, query: str, metadata: Optional[dict] = None) -> None:
        self._ctx = self._recorder.start_trace(
            query_text=query,
            pipeline_id=self._pipeline_id,
            metadata=metadata or {},
        )

    async def on_retrieve_end(self, nodes: List[Any], latency_ms: float, stage_id: str = "retriever") -> None:
        if not self._ctx:
            return
        docs = []
        for i, node in enumerate(nodes):
            text = getattr(node, "text", None) or getattr(node, "get_content", lambda: "")()
            node_id = getattr(node, "node_id", None) or getattr(node, "id_", str(i))
            score = float(getattr(node, "score", 0) or 0)
            docs.append(Document(id=str(node_id), text=str(text), score=score, rank=i + 1))
        self._ctx.stage(stage_id, docs, latency_ms)
        self._ctx.set_results(docs)
        await self._recorder.finish_trace(self._ctx)
        self._ctx = None


try:
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler

    _LI_AVAILABLE = True
except ImportError:
    BaseCallbackHandler = object  # type: ignore[misc,assignment]
    _LI_AVAILABLE = False


def _li_nodes_to_retobs(nodes: List[Any]) -> List[Document]:
    """Convert LlamaIndex NodeWithScore / TextNode objects to retobs Documents."""
    docs = []
    for i, node in enumerate(nodes):
        score = float(getattr(node, "score", 0) or 0)
        inner = getattr(node, "node", node)
        text = getattr(inner, "text", None) or getattr(inner, "get_content", lambda: "")()
        node_id = getattr(inner, "node_id", None) or getattr(inner, "id_", str(i))
        docs.append(Document(id=str(node_id), text=str(text), score=score, rank=i + 1))
    return docs


def _li_nodes_to_candidates(nodes: List[Any], op_id: str) -> List[Candidate]:
    """Convert LlamaIndex NodeWithScore / TextNode objects to V2 Candidates."""
    candidates: List[Candidate] = []
    for i, node in enumerate(nodes):
        score = float(getattr(node, "score", 0) or 0)
        inner = getattr(node, "node", node)
        node_id = getattr(inner, "node_id", None) or getattr(inner, "id_", str(i))
        candidates.append(Candidate(doc_id=str(node_id), score=score, rank=i + 1, origin_op_ids=[op_id]))
    return candidates


# ---------------------------------------------------------------------------
# Legacy (V1) zero-touch callback
# ---------------------------------------------------------------------------

class RetobsLlamaIndexCallback(BaseCallbackHandler):  # type: ignore[misc]
    """Real LlamaIndex BaseCallbackHandler subclass for zero-touch trace emission.

    .. deprecated:: Phase 5
        Prefer ``RetobsLlamaIndexCallbackV2`` for new code.  This class emits V1
        ``RetrievalTrace`` objects via ``TraceRecorder``.
    """

    def __init__(self, recorder: TraceRecorder, pipeline_id: str = "default"):
        if not _LI_AVAILABLE:
            raise ImportError(
                "RetobsLlamaIndexCallback requires llama-index-core. "
                "Install with: pip install retrieval-observatory[llamaindex]"
            )
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        self._event_start: Dict[str, float] = {}
        self._current_query: str = ""
        self._ctx: Optional[_TraceContext] = None

    def on_event_start(
        self,
        event_type: Any,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        from llama_index.core.callbacks.schema import CBEventType, EventPayload

        self._event_start[event_id] = time.monotonic()

        if event_type == CBEventType.QUERY:
            if payload:
                self._current_query = payload.get(EventPayload.QUERY_STR, "")

        if event_type in (CBEventType.RETRIEVE, CBEventType.RERANKING):
            if payload and not self._current_query:
                self._current_query = payload.get(EventPayload.QUERY_STR, "")

        return event_id

    def on_event_end(
        self,
        event_type: Any,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        from llama_index.core.callbacks.schema import CBEventType, EventPayload

        start = self._event_start.pop(event_id, None)
        latency_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0

        if event_type == CBEventType.RETRIEVE:
            nodes = (payload or {}).get(EventPayload.NODES, [])
            docs = _li_nodes_to_retobs(nodes)
            if self._ctx is None:
                self._ctx = self._recorder.start_trace(
                    query_text=self._current_query,
                    pipeline_id=self._pipeline_id,
                )
            self._ctx.stage("retriever", docs, latency_ms)

        elif event_type == CBEventType.RERANKING:
            nodes = (payload or {}).get(EventPayload.NODES, [])
            docs = _li_nodes_to_retobs(nodes)
            if self._ctx is not None:
                self._ctx.stage("reranker", docs, latency_ms)

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        self._current_query = ""
        self._ctx = None

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        if self._ctx is not None:
            if self._ctx.trace.snapshots:
                self._ctx.set_results(self._ctx.trace.snapshots[-1].documents)
            self._recorder.finish_trace_sync(self._ctx)
            self._ctx = None


# ---------------------------------------------------------------------------
# V2 zero-touch callback — builds OperatorSpan / RetrievalTraceV2
# ---------------------------------------------------------------------------

class RetobsLlamaIndexCallbackV2(BaseCallbackHandler):  # type: ignore[misc]
    """LlamaIndex BaseCallbackHandler that emits V2 traces (OperatorSpan DAG).

    RETRIEVE event → SOURCE span, RERANKING event → RERANK span.
    """

    def __init__(self, recorder: TraceRecorderV2, pipeline_id: str = "default"):
        if not _LI_AVAILABLE:
            raise ImportError(
                "RetobsLlamaIndexCallbackV2 requires llama-index-core. "
                "Install with: pip install retrieval-observatory[llamaindex]"
            )
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        self._event_start: Dict[str, float] = {}
        self._current_query: str = ""
        self._ctx: Optional[_TraceContextV2] = None

    def on_event_start(
        self,
        event_type: Any,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        from llama_index.core.callbacks.schema import CBEventType, EventPayload

        self._event_start[event_id] = time.monotonic()

        if event_type == CBEventType.QUERY:
            if payload:
                self._current_query = payload.get(EventPayload.QUERY_STR, "")

        if event_type in (CBEventType.RETRIEVE, CBEventType.RERANKING):
            if payload and not self._current_query:
                self._current_query = payload.get(EventPayload.QUERY_STR, "")

        return event_id

    def on_event_end(
        self,
        event_type: Any,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        from llama_index.core.callbacks.schema import CBEventType, EventPayload

        start = self._event_start.pop(event_id, None)
        latency_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0

        if event_type == CBEventType.RETRIEVE:
            nodes = (payload or {}).get(EventPayload.NODES, [])
            if self._ctx is None:
                self._ctx = self._recorder.start_trace(
                    query_text=self._current_query,
                    pipeline_id=self._pipeline_id,
                )
            op_id = f"source_{uuid.uuid4().hex[:8]}"
            candidates = _li_nodes_to_candidates(nodes, op_id)
            span = OperatorSpan(
                op_id=op_id,
                op_type="SOURCE",
                op_name="retriever",
                parent_ids=[],
                status="FIRED",
                deterministic=False,
                replay_policy="NOT_REPLAYABLE",
                latency_ms=latency_ms,
                outputs=candidates,
            )
            self._ctx.add_span(span)

        elif event_type == CBEventType.RERANKING:
            nodes = (payload or {}).get(EventPayload.NODES, [])
            if self._ctx is not None:
                op_id = f"rerank_{uuid.uuid4().hex[:8]}"
                candidates = _li_nodes_to_candidates(nodes, op_id)
                parent_ids = [self._ctx.trace.spans[-1].op_id] if self._ctx.trace.spans else []
                span = OperatorSpan(
                    op_id=op_id,
                    op_type="RERANK",
                    op_name="reranker",
                    parent_ids=parent_ids,
                    status="FIRED",
                    deterministic=False,
                    replay_policy="NOT_REPLAYABLE",
                    latency_ms=latency_ms,
                    outputs=candidates,
                )
                self._ctx.add_span(span)

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        self._current_query = ""
        self._ctx = None

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        if self._ctx is not None:
            self._recorder.finish_trace_sync(self._ctx)
            self._ctx = None
