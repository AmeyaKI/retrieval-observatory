"""Minimal FastAPI mock retrieval server for the HTTP adapter quickstart.

Run with:
    pip install fastapi uvicorn rank-bm25
    uvicorn server:app --port 8000

Then benchmark it:
    retobs run --config config.yaml
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    raise SystemExit("Install rank-bm25: pip install rank-bm25")

CORPUS = {
    "doc1": "Retrieval-augmented generation combines dense retrieval with language model generation.",
    "doc2": "BM25 is a sparse bag-of-words retrieval function based on term frequency and inverse document frequency.",
    "doc3": "Dense retrieval encodes queries and documents into vector embeddings and retrieves by cosine similarity.",
    "doc4": "Hybrid retrieval fuses sparse and dense signals using Reciprocal Rank Fusion or learned weights.",
    "doc5": "Rerankers use cross-encoder models to rescore candidate documents for improved precision.",
    "doc6": "NDCG@10 measures the ranking quality of the top-10 retrieved documents weighted by relevance grade.",
    "doc7": "Recall@K measures the fraction of relevant documents found in the top-K retrieved results.",
    "doc8": "A retrieval pipeline consists of one or more stages: retriever, optional reranker, optional filter.",
}

_doc_ids = list(CORPUS.keys())
_tokenized = [CORPUS[d].lower().split() for d in _doc_ids]
_bm25 = BM25Okapi(_tokenized)

app = FastAPI(title="retobs HTTP quickstart server")


class SearchRequest(BaseModel):
    query: str
    k: int = 10


class SearchResult(BaseModel):
    id: str
    text: str
    score: float


class SearchResponse(BaseModel):
    documents: list[SearchResult]


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    scores = _bm25.get_scores(req.query.lower().split())
    top_k = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: req.k]
    return SearchResponse(
        documents=[
            SearchResult(id=_doc_ids[i], text=CORPUS[_doc_ids[i]], score=float(scores[i]))
            for i in top_k
        ]
    )
