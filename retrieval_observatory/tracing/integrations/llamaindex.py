"""LlamaIndex callback integration for TraceLens."""
from __future__ import annotations

from typing import Any, List, Optional

from retrieval_observatory.tracing.recorder import TraceRecorder, _TraceContext
from retrieval_observatory.types import Document


class RetobsLlamaIndexHandler:
    """Hook wrapper for LlamaIndex retrieval events → TraceRecorder."""

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
