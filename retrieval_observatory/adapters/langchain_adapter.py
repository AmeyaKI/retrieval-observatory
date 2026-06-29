from __future__ import annotations

import asyncio
import hashlib
import time
import warnings

from retrieval_observatory.types import Document, Query, RetrievalResult


class LangChainAdapter:
    """Wraps any LangChain BaseRetriever into the retobs interface.

    Note: Query.filters are not forwarded to the underlying LangChain retriever.
    """

    supports_filters: bool = False

    def __init__(self, retriever, retriever_id: str):
        self.retriever_id = retriever_id
        self._retriever = retriever

    async def retrieve(self, query: Query) -> RetrievalResult:
        if query.filters:
            warnings.warn(
                f"LangChainAdapter ({self.retriever_id!r}) does not forward Query.filters "
                "to the underlying retriever; filters are ignored.",
                UserWarning,
                stacklevel=2,
            )
        start = time.perf_counter()
        if asyncio.iscoroutinefunction(self._retriever.ainvoke):
            lc_docs = await self._retriever.ainvoke(query.text)
        else:
            lc_docs = await asyncio.to_thread(self._retriever.invoke, query.text)
        latency_ms = (time.perf_counter() - start) * 1000

        documents = []
        for rank, doc in enumerate(lc_docs[: query.k], start=1):
            doc_id = doc.metadata.get("id") or doc.metadata.get("doc_id")
            if doc_id is None:
                # Derive stable ID from content hash
                doc_id = hashlib.md5(doc.page_content.encode()).hexdigest()
            documents.append(
                Document(
                    id=str(doc_id),
                    text=doc.page_content,
                    score=doc.metadata.get("score", 0.0),
                    rank=rank,
                    metadata=doc.metadata,
                )
            )

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )
