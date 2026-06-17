"""LangChain callback integration for TraceLens."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from retrieval_observatory.tracing.recorder import TraceRecorder, _TraceContext
from retrieval_observatory.types import Document


class RetobsTraceHandler:
    """LangChain-compatible callback that emits retrieval stages to TraceRecorder."""

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
