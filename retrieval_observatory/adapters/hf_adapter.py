from __future__ import annotations

import asyncio
import time
import warnings
from typing import List

from retrieval_observatory.types import Document, Query, RetrievalResult


class HFCrossEncoderAdapter:
    """Reranks candidates using a local HuggingFace cross-encoder model."""

    def __init__(self, model_name: str, retriever_id: str = "hf_crossencoder", batch_size: int = 32):
        self.retriever_id = retriever_id
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise ImportError(
                    "HuggingFace adapter requires sentence-transformers. "
                    "Install with: pip install retobs[hf]"
                ) from e
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"`resume_download` is deprecated and will be removed in version 1\.0\.0\.",
                    category=FutureWarning,
                    module=r"huggingface_hub\.file_download",
                )
                self._model = CrossEncoder(self.model_name)
        return self._model

    def _score_sync(self, query_text: str, documents: List[Document]) -> List[float]:
        model = self._load_model()
        pairs = [[query_text, doc.text] for doc in documents]
        scores = []
        for i in range(0, len(pairs), self.batch_size):
            batch = pairs[i : i + self.batch_size]
            batch_scores = model.predict(batch).tolist()
            scores.extend(batch_scores)
        return scores

    async def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        start = time.perf_counter()
        scores = await asyncio.to_thread(self._score_sync, query.text, documents)
        latency_ms = (time.perf_counter() - start) * 1000

        scored = sorted(
            zip(documents, scores), key=lambda x: x[1], reverse=True
        )
        reranked = [
            Document(
                id=doc.id,
                text=doc.text,
                score=float(score),
                rank=rank,
                title=doc.title,
                timestamp=doc.timestamp,
                metadata=doc.metadata,
            )
            for rank, (doc, score) in enumerate(scored[: query.k], start=1)
        ]

        return RetrievalResult(
            documents=reranked,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )
