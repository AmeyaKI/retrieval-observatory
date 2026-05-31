from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import httpx

from retrieval_observatory.types import Document, Query, RetrievalResult


class HTTPAdapter:
    """Wraps any REST endpoint as a retrieval stage.

    Request (POST, JSON body):
        {"query": "<text>", "k": <int>}
        {"query": "<text>", "k": <int>, "filters": {...}}  # only when filters present

    Response (JSON) — two accepted shapes:
        {"documents": [{"id": "...", "text": "...", "score": 0.9}, ...]}
        [{"id": "...", "text": "...", "score": 0.9}, ...]   # bare list also accepted

    Field names are configurable via id_field / text_field / score_field.
    If a document is missing the configured id_field, a clear ValueError is raised
    showing which fields were actually present, to diagnose misconfigurations quickly.

    Example YAML stage config:
        - type: adapter.http
          url: http://localhost:8080/retrieve
          config:
            k: 100
            id_field: doc_id      # default: "id"
            text_field: content   # default: "text"
            score_field: relevance # default: "score"
    """

    def __init__(
        self,
        url: str,
        retriever_id: str,
        id_field: str = "id",
        text_field: str = "text",
        score_field: str = "score",
        timeout: float = 10.0,
        retry_attempts: int = 2,
    ):
        self.url = url
        self.retriever_id = retriever_id
        self.id_field = id_field
        self.text_field = text_field
        self.score_field = score_field
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def retrieve(self, query: Query) -> RetrievalResult:
        payload: Dict[str, Any] = {"query": query.text, "k": query.k}
        if query.filters:
            payload["filters"] = query.filters

        start = time.perf_counter()
        client = self._get_client()
        response = None
        retries = 0
        for attempt in range(self.retry_attempts + 1):
            try:
                response = await client.post(self.url, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.retry_attempts:
                    retries += 1
                    await response.aclose()
                    await asyncio.sleep(2 ** attempt * 0.25)
                    continue
                break
            except httpx.RequestError:
                if attempt >= self.retry_attempts:
                    raise
                retries += 1
                await asyncio.sleep(2 ** attempt * 0.25)
        latency_ms = (time.perf_counter() - start) * 1000

        if response is None:
            raise RuntimeError("HTTP adapter failed to receive a response")
        response.raise_for_status()
        data = response.json()

        raw_docs: List[Dict] = data.get("documents", data) if isinstance(data, dict) else data
        if not isinstance(raw_docs, list):
            raise ValueError(
                f"HTTP adapter: expected a JSON list or {{\"documents\": [...]}} from {self.url}, "
                f"got {type(raw_docs).__name__}. Response keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}"
            )
        documents = []
        for i, doc in enumerate(raw_docs):
            if self.id_field not in doc:
                sample_keys = list(doc.keys())[:6]
                raise ValueError(
                    f"HTTP adapter: document {i} from {self.url} is missing id field "
                    f"'{self.id_field}'. Available fields: {sample_keys}. "
                    f"Set config.id_field to match your server's response schema."
                )
            documents.append(Document(
                id=str(doc[self.id_field]),
                text=doc.get(self.text_field, ""),
                score=float(doc.get(self.score_field, 0.0)),
                rank=i + 1,
            ))

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"network_ms": latency_ms, "compute_ms": 0.0, "retries": float(retries)},
        )
