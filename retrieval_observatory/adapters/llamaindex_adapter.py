from __future__ import annotations

import asyncio
import hashlib
import time

from retrieval_observatory.types import Document, Query, RetrievalResult


class LlamaIndexAdapter:
    """Wraps any LlamaIndex BaseRetriever into the retobs interface."""

    def __init__(self, retriever, retriever_id: str):
        self.retriever_id = retriever_id
        self._retriever = retriever

    async def retrieve(self, query: Query) -> RetrievalResult:
        start = time.perf_counter()
        if asyncio.iscoroutinefunction(self._retriever.aretrieve):
            nodes = await self._retriever.aretrieve(query.text)
        else:
            nodes = await asyncio.to_thread(self._retriever.retrieve, query.text)
        latency_ms = (time.perf_counter() - start) * 1000

        documents = []
        for rank, node_with_score in enumerate(nodes[: query.k], start=1):
            node = node_with_score.node
            doc_id = node.node_id or hashlib.md5(node.get_content().encode()).hexdigest()
            documents.append(
                Document(
                    id=str(doc_id),
                    text=node.get_content(),
                    score=node_with_score.score or 0.0,
                    rank=rank,
                    metadata=node.metadata,
                )
            )

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )
