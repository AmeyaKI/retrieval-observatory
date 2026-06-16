#!/usr/bin/env python3
"""Minimal instrumented BM25 search API for TraceLens demo.

Run::

    pip install retrieval-observatory[dashboard,demo]
    python examples/fastapi_search/app.py

Then fire requests and inspect traces via ``retobs serve`` → TraceLens mode.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from rank_bm25 import BM25Okapi

from retrieval_observatory.tracing import TraceRecorder, MemorySink
from retrieval_observatory.tracing.integrations.fastapi import get_trace, instrument_fastapi
from retrieval_observatory.types import Document

CORPUS = [
    {"id": "d1", "text": "Retrieval observatory benchmarks hybrid RAG pipelines."},
    {"id": "d2", "text": "BM25 is a lexical sparse retriever based on term frequency."},
    {"id": "d3", "text": "Dense embeddings capture semantic similarity between queries and documents."},
]

app = FastAPI(title="FastAPI Search Demo")
recorder = TraceRecorder(service="fastapi-search", sink=MemorySink())
instrument_fastapi(app, recorder, pipeline_id="bm25")


def _build_index():
    tokenized = [doc["text"].lower().split() for doc in CORPUS]
    return BM25Okapi(tokenized)


_bm25 = _build_index()


@app.get("/search")
async def search(q: str, request: Request, k: int = 3):
    t = get_trace(request)
    start = time.perf_counter()
    scores = _bm25.get_scores(q.lower().split())
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
    docs = [
        Document(id=CORPUS[i]["id"], text=CORPUS[i]["text"], score=float(s), rank=r + 1)
        for r, (i, s) in enumerate(ranked)
    ]
    latency_ms = (time.perf_counter() - start) * 1000
    if t:
        t.stage("bm25", docs, latency_ms)
        t.set_results(docs)
    return {"query": q, "results": [{"id": d.id, "score": d.score, "text": d.text} for d in docs]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
