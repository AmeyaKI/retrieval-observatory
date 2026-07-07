"""Self-correcting retriever: retrieve, critique the top result's confidence, and retry
with an expanded query if confidence is low. Demonstrates the retrieve-critique-retry
pattern — a genuinely non-linear topology, not just a cosmetic rerank stage."""
from __future__ import annotations

import time
from typing import Dict, List, Tuple

from retrieval_observatory.types import Document, Query, RetrievalResult

# Toy domain-specific expansion dictionary; a production system would call an LLM or a
# thesaurus/embedding service here. Kept deterministic and dependency-free for the demo.
_EXPANSIONS = {
    "car": ["automobile", "vehicle"],
    "buy": ["purchase", "acquire"],
    "cheap": ["affordable", "inexpensive"],
    "fast": ["quick", "rapid"],
    "doctor": ["physician", "gp"],
}


class FirstPassRetriever:
    """Plain keyword-overlap retriever — the initial retrieval pass."""

    def __init__(self, corpus: Dict[str, str], retriever_id: str = "first_pass"):
        self.retriever_id = retriever_id
        self._corpus = corpus

    def retrieve(self, query: Query) -> RetrievalResult:
        start = time.perf_counter()
        documents = _score_corpus(self._corpus, query.text, query.k)
        return RetrievalResult(
            documents=documents,
            latency_ms=(time.perf_counter() - start) * 1000,
            retriever_id=self.retriever_id,
        )


class CritiqueRetryReranker:
    """Critiques the first pass: if the top score (normalized by query length) is below
    `confidence_threshold`, expands the query with synonyms and retries retrieval, merging
    in any newly discovered documents. A real second retrieval call driven by a real
    quality judgment on the first pass — not a cosmetic rerank."""

    def __init__(
        self,
        corpus: Dict[str, str],
        confidence_threshold: float = 0.15,
        retriever_id: str = "critique_retry",
    ):
        self.retriever_id = retriever_id
        self._corpus = corpus
        self._confidence_threshold = confidence_threshold

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        start = time.perf_counter()
        top_score = documents[0].score if documents else 0.0
        normalized_top = top_score / max(len(query.text.split()), 1)
        retried = False
        if normalized_top < self._confidence_threshold:
            retried = True
            expanded_text = _expand_query(query.text)
            retry_docs = _score_corpus(self._corpus, expanded_text, query.k)
            documents = _merge_by_id(documents, retry_docs)[: query.k]
        return RetrievalResult(
            documents=documents,
            latency_ms=(time.perf_counter() - start) * 1000,
            retriever_id=self.retriever_id,
            profiling={"critique_retried": 1.0 if retried else 0.0},
        )


def _score_corpus(corpus: Dict[str, str], text: str, k: int) -> List[Document]:
    q_tokens = set(text.lower().split())
    scored: List[Tuple[str, float]] = []
    for doc_id, doc_text in corpus.items():
        overlap = len(q_tokens & set(doc_text.lower().split()))
        if overlap > 0:
            scored.append((doc_id, float(overlap)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [
        Document(id=doc_id, text=corpus[doc_id], score=score, rank=rank)
        for rank, (doc_id, score) in enumerate(scored[:k], start=1)
    ]


def _expand_query(text: str) -> str:
    tokens = text.lower().split()
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(_EXPANSIONS.get(token, []))
    return " ".join(expanded)


def _merge_by_id(primary: List[Document], secondary: List[Document]) -> List[Document]:
    seen = {doc.id for doc in primary}
    merged = list(primary)
    for doc in secondary:
        if doc.id not in seen:
            merged.append(doc)
            seen.add(doc.id)
    merged.sort(key=lambda doc: doc.score, reverse=True)
    for rank, doc in enumerate(merged, start=1):
        doc.rank = rank
    return merged


def build_first_pass_retriever(
    corpus: Dict[str, str] | None,
    stage_cfg: dict,
    **kwargs,
) -> Tuple[FirstPassRetriever, int]:
    if corpus is None:
        raise ValueError("FirstPassRetriever requires a corpus from the dataset loader.")
    cfg = stage_cfg.get("config", {})
    k = int(cfg.get("k", 10))
    return FirstPassRetriever(corpus, retriever_id=stage_cfg.get("retriever_id", "first_pass")), k


def build_critique_retry_reranker(
    corpus: Dict[str, str] | None,
    stage_cfg: dict,
    **kwargs,
) -> Tuple[CritiqueRetryReranker, int]:
    if corpus is None:
        raise ValueError("CritiqueRetryReranker requires a corpus from the dataset loader.")
    cfg = stage_cfg.get("config", {})
    k = int(cfg.get("k", 10))
    threshold = float(cfg.get("confidence_threshold", 0.15))
    retriever_id = stage_cfg.get("retriever_id", "critique_retry")
    return CritiqueRetryReranker(corpus, confidence_threshold=threshold, retriever_id=retriever_id), k
