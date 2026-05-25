from __future__ import annotations

import time
from typing import Any, Dict, List

import httpx

from retrieval_observatory.types import Document, Query, RetrievalResult


class HTTPAdapter:
    """Wraps any REST endpoint implementing POST {query, k} → {documents: [...]}."""

    def __init__(
        self,
        url: str,
        retriever_id: str,
        id_field: str = "id",
        text_field: str = "text",
        score_field: str = "score",
        timeout: float = 10.0,
    ):
        self.url = url
        self.retriever_id = retriever_id
        self.id_field = id_field
        self.text_field = text_field
        self.score_field = score_field
        self.timeout = timeout

    async def retrieve(self, query: Query) -> RetrievalResult:
        payload: Dict[str, Any] = {"query": query.text, "k": query.k}
        if query.filters:
            payload["filters"] = query.filters

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, json=payload)
        latency_ms = (time.perf_counter() - start) * 1000

        response.raise_for_status()
        data = response.json()

        raw_docs: List[Dict] = data.get("documents", data) if isinstance(data, dict) else data
        documents = [
            Document(
                id=str(doc[self.id_field]),
                text=doc.get(self.text_field, ""),
                score=float(doc.get(self.score_field, 0.0)),
                rank=i + 1,
            )
            for i, doc in enumerate(raw_docs)
        ]

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
        )
