from __future__ import annotations

import time
from typing import Any, Mapping, Sequence
from uuid import UUID

from retrieval_observatory.tracing.integrations.operator_registry import ComponentEvent, OperatorRegistry
from retrieval_observatory.tracing.recorder import TraceContext, TraceRecorder

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:
    BaseCallbackHandler = object  # type: ignore[misc,assignment]


def _path(serialized: Mapping[str, Any] | None, kwargs: Mapping[str, Any]) -> tuple[str, str]:
    """The component path and whether it identifies the component (``stable``) or is the
    generic fallback shared by every unserialised retriever (``unstable``)."""
    if kwargs.get("component_path"):
        return str(kwargs["component_path"]), "stable"
    value = (serialized or {}).get("id") or (serialized or {}).get("name")
    if isinstance(value, (list, tuple)):
        return ".".join(str(item) for item in value), "stable"
    return (str(value), "stable") if value else ("retriever", "unstable")


def _query(inputs: Any) -> str:
    if isinstance(inputs, str):
        return inputs
    if isinstance(inputs, Mapping):
        for key in ("query", "question", "input", "human_input"):
            if key in inputs:
                return str(inputs[key])
    return ""


class RetobsLangChainCallback(BaseCallbackHandler):  # type: ignore[misc]
    """Manifest-backed LangChain callback with stable graph identity."""

    def __init__(self, recorder: TraceRecorder, registry: OperatorRegistry, pipeline_id: str = "default"):
        super().__init__()
        self.recorder, self.registry, self.pipeline_id = recorder, registry, pipeline_id
        self._traces: dict[UUID, TraceContext] = {}
        self._root_of: dict[UUID, UUID] = {}
        self._starts: dict[UUID, tuple[float, str, str]] = {}

    def on_chain_start(self, serialized, inputs, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs):
        if parent_run_id is None:
            self._traces[run_id] = self.recorder.start_trace(
                _query(inputs), self.pipeline_id, metadata=dict(kwargs.get("metadata") or {})
            )
            self._root_of[run_id] = run_id
        elif parent_run_id in self._root_of:
            self._root_of[run_id] = self._root_of[parent_run_id]

    def on_retriever_start(self, serialized, query: str, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs):
        root = self._root_of.get(parent_run_id or run_id, parent_run_id or run_id)
        self._root_of[run_id] = root
        self._starts[run_id] = (time.monotonic(), *_path(serialized, kwargs))

    def on_retriever_end(self, documents: Sequence[Any], *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs):
        started, path, identity = self._starts.pop(run_id)
        root = self._root_of.get(run_id, parent_run_id or run_id)
        context = self._traces.get(root)
        if context is None:
            return
        parent_run_ids = (str(parent_run_id),) if parent_run_id else ()
        resolved = self.registry.resolve(ComponentEvent(path, str(run_id), parent_run_ids))
        # The framework's parent run is usually the chain, not a candidate producer: it is kept
        # for verification but never turned into a dataflow edge.
        context.span(
            resolved.op_type, resolved.op_id, documents, (time.monotonic() - started) * 1000,
            op_id=resolved.op_id, parent_ids=resolved.parent_ids, invocation_id=str(run_id),
            params={"framework_parent_run_ids": list(parent_run_ids), "component_identity": identity},
        )

    def on_retriever_error(self, error, *, run_id: UUID, **kwargs):
        self._starts.pop(run_id, None)

    def on_chain_end(self, outputs, *, run_id: UUID, **kwargs):
        context = self._traces.pop(run_id, None)
        if context:
            self.recorder.finish(context)
        self._root_of.pop(run_id, None)

    def on_chain_error(self, error, *, run_id: UUID, **kwargs):
        context = self._traces.pop(run_id, None)
        if context:
            self.recorder.finish(context, status="ERROR", error=error)
        self._root_of.pop(run_id, None)


LangChainRetrievalCallback = RetobsLangChainCallback
