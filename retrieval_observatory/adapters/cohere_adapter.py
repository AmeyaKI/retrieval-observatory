from __future__ import annotations

import time
from typing import List

from retrieval_observatory.types import Document, Query, RetrievalResult


class CohereRerankAdapter:
    """Reranks a candidate list using the Cohere Rerank API.

    Note: Query.filters are not forwarded to Cohere Rerank; filters are ignored.
    """

    supports_filters: bool = False

    def __init__(
        self,
        api_key: str,
        model: str = "rerank-english-v3.0",
        retriever_id: str = "cohere_rerank",
    ):
        self.retriever_id = retriever_id
        self.model = model
        self._api_key = api_key

    async def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        try:
            import cohere
        except ImportError as e:
            raise ImportError(
                "Cohere support requires 'cohere'. Install with: pip install retrieval-observatory[cohere]"
            ) from e

        client = cohere.AsyncClient(api_key=self._api_key)
        texts = [doc.text for doc in documents]

        start = time.perf_counter()
        response = await client.rerank(
            model=self.model,
            query=query.text,
            documents=texts,
            top_n=query.k,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        reranked: List[Document] = []
        for rank, result in enumerate(response.results, start=1):
            original_doc = documents[result.index]
            reranked.append(
                Document(
                    id=original_doc.id,
                    text=original_doc.text,
                    score=result.relevance_score,
                    rank=rank,
                    timestamp=original_doc.timestamp,
                    metadata=original_doc.metadata,
                )
            )

        return RetrievalResult(
            documents=reranked,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"network_ms": latency_ms, "compute_ms": 0.0, "retries": 0.0},
        )
