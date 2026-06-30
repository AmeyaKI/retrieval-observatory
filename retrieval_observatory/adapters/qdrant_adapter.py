from __future__ import annotations

import time
import warnings
from typing import Any, Callable

from retrieval_observatory.types import Document, Query, RetrievalResult


class QdrantAdapter:
    supports_filters: bool = True

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        retriever_id: str = "qdrant",
        embedding_fn: Callable[[str], list[float]] | None = None,
        api_key: str | None = None,
    ):
        self.retriever_id = retriever_id
        self._url = url
        self._collection_name = collection_name
        self._embedding_fn = embedding_fn
        self._api_key = api_key

    def _build_filter(self, query: Query) -> Any:
        if not query.filters:
            return None
        try:
            from qdrant_client.http import models as rest
        except ImportError:
            return None
        must = [rest.FieldCondition(key=key, match=rest.MatchValue(value=value)) for key, value in query.filters.items()]
        return rest.Filter(must=must)

    def retrieve(self, query: Query) -> RetrievalResult:
        try:
            from qdrant_client import QdrantClient
        except ImportError as e:
            raise ImportError(
                "QdrantAdapter requires qdrant-client. Install with: pip install qdrant-client"
            ) from e
        if self._embedding_fn is None:
            raise RuntimeError("QdrantAdapter requires embedding_fn for query vectors")

        start = time.perf_counter()
        client = QdrantClient(url=self._url, api_key=self._api_key)
        query_vector = self._embedding_fn(query.text)
        query_filter = self._build_filter(query)
        if query.filters and query_filter is None:
            warnings.warn("Qdrant filters provided but could not build filter payload; returning unfiltered results")
        points = client.search(
            collection_name=self._collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=query.k,
            with_payload=True,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        documents = []
        for rank, point in enumerate(points, start=1):
            payload = point.payload or {}
            documents.append(
                Document(
                    id=str(point.id),
                    text=str(payload.get("text", "")),
                    score=float(point.score),
                    rank=rank,
                    metadata={k: v for k, v in payload.items() if k != "text"},
                )
            )
        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"network_ms": latency_ms, "compute_ms": 0.0, "retries": 0.0},
        )
