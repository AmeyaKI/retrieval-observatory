#!/usr/bin/env python3
"""Minimal instrumented BM25 search API.

Run::

    pip install retrieval-observatory[dashboard,demo]
    python examples/integrations/fastapi_search/app.py

Traces are written to the demo DB by default so ``retobs serve --db .retobs/demo/results.db``
shows live + seeded traces together.

Environment:
    RETOBS_DB — SQLite path (default: .retobs/demo/results.db)
    RETOBS_TRACE_SERVICE — service name (default: demo)
    RETOBS_MEMORY_SINK=1 — keep traces in memory instead of the SQLite store
"""
from __future__ import annotations

import argparse
import os
import time

from fastapi import FastAPI, Request
from rank_bm25 import BM25Okapi

import retrieval_observatory as ro
from retrieval_observatory.tracing import BufferedTraceSink, MemoryExporter, TraceRecorder
from retrieval_observatory.tracing.integrations.fastapi import get_trace, instrument_fastapi

CORPUS = [
    {"id": "d1", "text": "Retrieval observatory benchmarks hybrid RAG pipelines."},
    {"id": "d2", "text": "BM25 is a lexical sparse retriever based on term frequency."},
    {"id": "d3", "text": "Dense embeddings capture semantic similarity between queries and documents."},
    {"id": "d4", "text": "Reranking improves precision by applying a cross-encoder to candidates."},
    {"id": "d5", "text": "RAG systems ground language model responses in retrieved documents."},
]

DEFAULT_DB = ".retobs/demo/results.db"
DEFAULT_SERVICE = "demo"


def _build_recorder(use_memory: bool) -> TraceRecorder:
    service = os.environ.get("RETOBS_TRACE_SERVICE", DEFAULT_SERVICE)
    if use_memory:
        return TraceRecorder(service, BufferedTraceSink(MemoryExporter(), service_id=service))
    return ro.init(service, os.environ.get("RETOBS_DB", DEFAULT_DB))


def create_app(use_memory: bool = False) -> FastAPI:
    app = FastAPI(title="FastAPI Search Demo")
    recorder = _build_recorder(use_memory)
    # One trace per request; the default query extractor reads ``?q=`` for query_text.
    instrument_fastapi(app, recorder, pipeline_id="bm25")

    tokenized = [doc["text"].lower().split() for doc in CORPUS]
    bm25 = BM25Okapi(tokenized)

    @app.get("/search")
    async def search(q: str, request: Request, k: int = 3):
        """Search endpoint. A query with no matching terms (e.g. 'xyzzy-qwerty') returns no candidates."""
        t = get_trace(request)
        start = time.perf_counter()
        scores = bm25.get_scores(q.lower().split())
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
        docs = [
            {"id": CORPUS[i]["id"], "score": float(s), "text": CORPUS[i]["text"]}
            for i, s in ranked
            if s > 0
        ]
        latency_ms = (time.perf_counter() - start) * 1000
        if t:
            t.span("SOURCE", "bm25", docs, latency_ms, op_id="bm25")
        return {"query": q, "results": docs}

    return app


app = create_app(use_memory=os.environ.get("RETOBS_MEMORY_SINK") == "1")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="FastAPI search demo with retobs tracing")
    parser.add_argument("--memory", action="store_true", help="Keep traces in memory instead of the SQLite store")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()
    uvicorn.run(create_app(use_memory=args.memory), host="0.0.0.0", port=args.port)
