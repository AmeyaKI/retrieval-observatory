"""Minimal custom retriever loaded via adapter.import."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from retobs.types import Document, Query, RetrievalResult


class KeywordOverlapRetriever:
    """Scores documents by token overlap with the query (demo only)."""

    def __init__(self, corpus: Dict[str, str], retriever_id: str = "keyword"):
        self.retriever_id = retriever_id
        self._corpus = corpus

    def retrieve(self, query: Query) -> RetrievalResult:
        start = time.perf_counter()
        q_tokens = set(query.text.lower().split())
        scored: List[Tuple[str, float]] = []
        for doc_id, text in self._corpus.items():
            overlap = len(q_tokens & set(text.lower().split()))
            if overlap > 0:
                scored.append((doc_id, float(overlap)))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: query.k]

        documents = [
            Document(
                id=doc_id,
                text=self._corpus[doc_id],
                score=score,
                rank=rank,
            )
            for rank, (doc_id, score) in enumerate(top, start=1)
        ]
        latency_ms = (time.perf_counter() - start) * 1000
        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
        )


def build_retriever(
    corpus: Optional[Dict[str, str]],
    stage_cfg: dict,
    **kwargs,
) -> Tuple[KeywordOverlapRetriever, int]:
    if corpus is None:
        raise ValueError("KeywordOverlapRetriever requires a corpus from the dataset loader.")
    cfg = stage_cfg.get("config", {})
    k = int(cfg.get("k", 10))
    retriever_id = stage_cfg.get("retriever_id", "keyword")
    return KeywordOverlapRetriever(corpus, retriever_id=retriever_id), k
