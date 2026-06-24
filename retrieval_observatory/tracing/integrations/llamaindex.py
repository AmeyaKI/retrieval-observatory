"""LlamaIndex callback integration for TraceLens."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from retrieval_observatory.tracing.recorder import TraceRecorder, _TraceContext
from retrieval_observatory.types import Document


class RetobsLlamaIndexHandler:
    """Hook wrapper for LlamaIndex retrieval events → TraceRecorder.

    This is the manual hook-based API (legacy).  For zero-touch integration,
    use RetobsLlamaIndexCallback instead.
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
        # NodeWithScore wraps a node; plain TextNode is also possible
        score = float(getattr(node, "score", 0) or 0)
        inner = getattr(node, "node", node)
        text = getattr(inner, "text", None) or getattr(inner, "get_content", lambda: "")()
        node_id = getattr(inner, "node_id", None) or getattr(inner, "id_", str(i))
        docs.append(Document(id=str(node_id), text=str(text), score=score, rank=i + 1))
    return docs


class RetobsLlamaIndexCallback(BaseCallbackHandler):  # type: ignore[misc]
    """Real LlamaIndex BaseCallbackHandler subclass for zero-touch trace emission.

    Usage::

        from llama_index.core.callbacks import CallbackManager
        from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexCallback

        cb = RetobsLlamaIndexCallback(recorder, pipeline_id="my-pipeline")
        Settings.callback_manager = CallbackManager([cb])
        # or pass to a query engine's CallbackManager

    Hooks RETRIEVE and RERANKING events.  Each top-level query produces one
    RetrievalTrace with one stage per retrieve/rerank event.
    """

    def __init__(self, recorder: TraceRecorder, pipeline_id: str = "default"):
        if not _LI_AVAILABLE:
            raise ImportError(
                "RetobsLlamaIndexCallback requires llama-index-core. "
                "Install with: pip install retobs[llamaindex]"
            )
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._recorder = recorder
        self._pipeline_id = pipeline_id
        # event_id → start time
        self._event_start: Dict[str, float] = {}
        # query text captured from the QUERY event or retrieve payload
        self._current_query: str = ""
        # active trace context (one per top-level trace)
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
        # Called at the start of a LlamaIndex query trace
        self._current_query = ""
        self._ctx = None

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        # Called at the end of a LlamaIndex query trace — flush if we have a context
        if self._ctx is not None:
            if self._ctx.trace.snapshots:
                self._ctx.set_results(self._ctx.trace.snapshots[-1].documents)
            self._recorder.finish_trace_sync(self._ctx)
            self._ctx = None
