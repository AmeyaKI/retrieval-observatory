"""Two retrieval lanes over a toy corpus. Each ``search`` method is a SOURCE operator.

Pure Python, no model downloads: the keyword lane counts token overlap (a stand-in for BM25),
the dense lane scores character-trigram Jaccard similarity (a stand-in for an embedding index).
"""
from __future__ import annotations

import re

from retrieval_observatory.sdk.observe import observe

CORPUS: dict[str, str] = {
    "d01": "BM25 is a lexical sparse retriever based on term frequency and document length.",
    "d02": "Dense embeddings capture semantic similarity between queries and documents.",
    "d03": "Reciprocal rank fusion merges ranked lists from several retrieval lanes.",
    "d04": "A cross-encoder reranker rescores the fused candidates for precision.",
    "d05": "Hybrid retrieval combines a keyword lane with a dense lane before reranking.",
    "d06": "Chunking long documents into passages improves recall for specific questions.",
    "d07": "Query expansion adds synonyms to the user query before lexical retrieval.",
    "d08": "Counterfactual replay removes one operator and re-scores the final results.",
    "d09": "Candidate lineage records where each document entered and left the pipeline.",
    "d10": "Retrieval traces persist every operator span with its parent edges.",
    "d11": "A FAISS index answers nearest-neighbour queries over embedding vectors.",
    "d12": "Evaluation sets pair queries with relevance judgements for recall and nDCG.",
    "d13": "Latency budgets bound the wall-clock time of each retrieval stage.",
    "d14": "A gate routes a query to the dense lane only when the keyword lane is weak.",
    "d15": "Reranking with a small model keeps precision high at a modest latency cost.",
    "d16": "Stop words are removed before tokenising the query for the keyword lane.",
    "d17": "A release policy compares baseline and candidate runs before promotion.",
    "d18": "The dashboard shows each production trace as an operator DAG with candidates.",
    "d19": "Deterministic fusion is replayed exactly; a reranker is replayed from observed scores.",
    "d20": "Hybrid search with reranking is the default architecture for RAG retrieval.",
}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _trigrams(text: str) -> set[str]:
    padded = f"  {text.lower()}  "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


class KeywordRetriever:
    """Token-overlap lane. ``op_id="keyword"`` is the name every downstream span refers to."""

    def __init__(self, corpus: dict[str, str] = CORPUS):
        self.corpus = corpus

    @observe("SOURCE", op_id="keyword", replay_policy="NOT_REPLAYABLE")
    def search(self, query: str, k: int = 10) -> list[dict]:
        query_tokens = tokens(query)
        hits = [
            {"doc_id": doc_id, "score": float(len(query_tokens & tokens(text))), "text": text}
            for doc_id, text in self.corpus.items()
        ]
        hits = [hit for hit in hits if hit["score"] > 0]
        hits.sort(key=lambda hit: (-hit["score"], hit["doc_id"]))
        return hits[:k]


class DenseRetriever:
    """Character-trigram Jaccard lane. ``op_id="dense"`` is the second parent of the fusion span."""

    def __init__(self, corpus: dict[str, str] = CORPUS):
        self.corpus = corpus
        self._index = {doc_id: _trigrams(text) for doc_id, text in corpus.items()}

    @observe("SOURCE", op_id="dense", replay_policy="NOT_REPLAYABLE")
    def search(self, query: str, k: int = 10) -> list[dict]:
        query_grams = _trigrams(query)
        hits = []
        for doc_id, grams in self._index.items():
            union = len(query_grams | grams)
            score = len(query_grams & grams) / union if union else 0.0
            hits.append({"doc_id": doc_id, "score": score, "text": self.corpus[doc_id]})
        hits.sort(key=lambda hit: (-hit["score"], hit["doc_id"]))
        return hits[:k]
