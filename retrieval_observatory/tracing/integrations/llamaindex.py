from __future__ import annotations

import time
from typing import Any, Mapping

from retrieval_observatory.tracing.integrations.operator_registry import ComponentEvent, OperatorRegistry
from retrieval_observatory.tracing.recorder import TraceContext, TraceRecorder

try:
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler
except ImportError:
    BaseCallbackHandler = object  # type: ignore[misc,assignment]


class RetobsLlamaIndexCallback(BaseCallbackHandler):  # type: ignore[misc]
    """Manifest-backed LlamaIndex callback with event-parent correlation."""

    def __init__(self, recorder: TraceRecorder, registry: OperatorRegistry, pipeline_id: str = "default"):
        try:
            super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        except TypeError:
            super().__init__()
        self.recorder, self.registry, self.pipeline_id = recorder, registry, pipeline_id
        self._context: TraceContext | None = None
        self._starts: dict[str, tuple[float, str, str]] = {}
        self._query = ""

    def on_event_start(self, event_type: Any, payload: Mapping[str, Any] | None = None, event_id: str = "", parent_id: str = "", **kwargs):
        payload = payload or {}
        name = str(getattr(event_type, "value", event_type)).lower()
        self._query = str(payload.get("query_str", payload.get("query", self._query)))
        if name in {"retrieve", "retrieving", "reranking", "rerank"}:
            path = str(kwargs.get("component_path") or payload.get("component_path") or name)
            self._starts[event_id] = (time.monotonic(), path, parent_id)
            if self._context is None:
                self._context = self.recorder.start_trace(self._query, self.pipeline_id)
        return event_id

    def on_event_end(self, event_type: Any, payload: Mapping[str, Any] | None = None, event_id: str = "", **kwargs):
        started = self._starts.pop(event_id, None)
        if started is None or self._context is None:
            return
        since, path, parent_id = started
        payload = payload or {}
        nodes = payload.get("nodes", payload.get("documents", ()))
        resolved = self.registry.resolve(ComponentEvent(path, event_id, (parent_id,) if parent_id else ()))
        self._context.span(
            resolved.op_type, resolved.op_id, nodes, (time.monotonic() - since) * 1000,
            op_id=resolved.op_id, parent_ids=resolved.parent_ids,
        )

    def start_trace(self, trace_id: str | None = None) -> None:
        self._context, self._query = None, ""

    def end_trace(self, trace_id: str | None = None, trace_map=None) -> None:
        if self._context:
            self.recorder.finish(self._context)
            self._context = None


LlamaIndexRetrievalCallback = RetobsLlamaIndexCallback
