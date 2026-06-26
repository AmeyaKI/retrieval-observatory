from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Dict, List

from retrieval_observatory.types import Document, Query, RetrievalResult


class RRFFusionAdapter:
    """Reciprocal Rank Fusion over multiple retrievers.

    Runs all sub-retrievers concurrently, then combines their ranked lists:
        score(doc) = Σ  1 / (rrf_k + rank_i(doc))
    across all retrievers that returned the document.

    Implements BaseRetriever protocol. Use as Stage 0 in a single-stage pipeline
    or as the first stage of a multi-stage pipeline (followed by a reranker).

    Typically paired with a sparse (BM25) and a dense retriever:
        retrieve candidates with bm25 and dense → RRF fuse → optional reranker

    rrf_k (default 60): RRF smoothing constant. Higher values reduce the impact
    of rank differences. Papers use 60; lower values (10-20) are more aggressive.
    fetch_k: how many candidates each sub-retriever fetches before fusion.
    """

    def __init__(
        self,
        retrievers: List,
        retriever_id: str = "rrf",
        rrf_k: int = 60,
        fetch_k: int = 100,
        top_k: int = 100,
    ):
        self.retriever_id = retriever_id
        self._retrievers = retrievers
        self._rrf_k = rrf_k
        self._fetch_k = fetch_k
        self._top_k = top_k

    async def retrieve(self, query: Query) -> RetrievalResult:
        fetch_query = replace(query, k=self._fetch_k)

        start = time.perf_counter()

        async def _call(retriever) -> RetrievalResult:
            if asyncio.iscoroutinefunction(retriever.retrieve):
                return await retriever.retrieve(fetch_query)
            return await asyncio.to_thread(retriever.retrieve, fetch_query)

        sub_results: List[RetrievalResult] = await asyncio.gather(
            *[_call(r) for r in self._retrievers]
        )

        fused_scores: Dict[str, float] = {}
        doc_store: Dict[str, Document] = {}

        for result in sub_results:
            for doc in result.documents:
                fused_scores[doc.id] = fused_scores.get(doc.id, 0.0) + 1.0 / (self._rrf_k + doc.rank)
                if doc.id not in doc_store:
                    doc_store[doc.id] = doc

        ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[: self._top_k]

        documents = [
            Document(
                id=doc_id,
                text=doc_store[doc_id].text,
                score=score,
                rank=rank + 1,
                title=doc_store[doc_id].title,
                timestamp=doc_store[doc_id].timestamp,
                metadata=doc_store[doc_id].metadata,
            )
            for rank, (doc_id, score) in enumerate(ranked)
        ]

        latency_ms = (time.perf_counter() - start) * 1000
        total_sub_latency = sum(r.latency_ms for r in sub_results)

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={
                "compute_ms": latency_ms,
                "network_ms": total_sub_latency,
                "retries": 0.0,
            },
            arm_results=sub_results,
        )
