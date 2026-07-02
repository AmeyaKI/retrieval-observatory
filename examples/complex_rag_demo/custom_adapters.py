"""Custom `adapter.import` stage for the complex RAG demo.

retobs's built-in adapters cover sources (BM25, dense, pgvector, Qdrant) and
rerankers (cross-encoder, Cohere), but a post-rerank *recency boost* is
pipeline-specific business logic, not something retobs ships. This is exactly
what `adapter.import` is for: plug a plain Python object with `.rerank()` into
any stage position, and it participates in caching, metrics, diagnostics, and
trace-native attribution like any built-in adapter.

Wired into a pipeline via (run with PYTHONPATH=examples/complex_rag_demo so the
bare module name resolves, matching examples/custom_retriever's convention):
    boost:
      type: adapter.import
      config:
        factory: custom_adapters:build_recency_boost
        window_days: 120
        multiplier: 1.15
        k: 10
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from retrieval_observatory.types import Document, Query, RetrievalResult

_CORPUS_PATH = Path(__file__).parent / "corpus.jsonl"


def _load_timestamps() -> Dict[str, datetime]:
    timestamps: Dict[str, datetime] = {}
    with open(_CORPUS_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ts = obj.get("timestamp")
            if ts:
                timestamps[obj["id"]] = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return timestamps


class RecencyBoostReranker:
    """Deterministic post-rerank boost: recently-timestamped docs get a score bump.

    retobs's YAML corpus loader (datasets/custom.py) only forwards plain text
    to BM25/dense adapters (see corpus vs corpus_documents), so Document.timestamp
    arrives as None by the time a document reaches this stage. This adapter loads
    its own doc_id -> timestamp lookup directly from corpus.jsonl instead.
    """

    def __init__(self, retriever_id: str = "freshness_boost", window_days: int = 120, multiplier: float = 1.15, k: int = 10):
        self.retriever_id = retriever_id
        self.window_days = window_days
        self.multiplier = multiplier
        self.k = k
        self._timestamps = _load_timestamps()

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        start = time.perf_counter()
        now = datetime.now(timezone.utc)
        boosted: List[Document] = []
        for doc in documents:
            ts = self._timestamps.get(doc.id)
            recent = ts is not None and (now - ts).days <= self.window_days
            new_score = doc.score * self.multiplier if recent else doc.score
            boosted.append(
                Document(
                    id=doc.id, text=doc.text, score=new_score, rank=doc.rank, title=doc.title,
                    timestamp=ts, metadata={**doc.metadata, "pre_boost_score": doc.score},
                )
            )
        boosted.sort(key=lambda d: d.score, reverse=True)
        k = query.k or self.k
        top = boosted[:k]
        for i, d in enumerate(top):
            d.rank = i + 1
        latency_ms = (time.perf_counter() - start) * 1000
        return RetrievalResult(documents=top, latency_ms=latency_ms, retriever_id=self.retriever_id)


def build_recency_boost(corpus, stage_cfg: dict, **_kwargs):
    cfg = stage_cfg.get("config", {})
    adapter = RecencyBoostReranker(
        retriever_id=stage_cfg.get("retriever_id", "freshness_boost"),
        window_days=cfg.get("window_days", 120),
        multiplier=cfg.get("multiplier", 1.15),
        k=cfg.get("k", 10),
    )
    return adapter, cfg.get("k", 10)
