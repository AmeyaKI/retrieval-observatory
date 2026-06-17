#!/usr/bin/env python3
"""Minimal instrumented BM25 search API for TraceLens demo.

Run::

    pip install retrieval-observatory[dashboard,demo]
    python examples/fastapi_search/app.py

Traces are written to the demo DB by default so ``retobs serve --db .retobs/demo/results.db``
shows live + seeded traces together.

Environment:
    RETOBS_DB — SQLite path (default: .retobs/demo/results.db)
    RETOBS_TRACE_SERVICE — service name (default: demo)
    RETOBS_MEMORY_SINK=1 — use in-memory sink instead of StoreSink
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time

from fastapi import FastAPI, Request
from rank_bm25 import BM25Okapi

from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing import MemorySink, TraceRecorder
from retrieval_observatory.tracing.integrations.fastapi import get_trace, instrument_fastapi
from retrieval_observatory.tracing.sink import StoreSink
from retrieval_observatory.types import Document

CORPUS = [
    {"id": "d1", "text": "Retrieval observatory benchmarks hybrid RAG pipelines."},
    {"id": "d2", "text": "BM25 is a lexical sparse retriever based on term frequency."},
    {"id": "d3", "text": "Dense embeddings capture semantic similarity between queries and documents."},
]

DEFAULT_DB = ".retobs/demo/results.db"
DEFAULT_SERVICE = "demo"


def _build_recorder(use_memory: bool) -> TraceRecorder:
    service = os.environ.get("RETOBS_TRACE_SERVICE", DEFAULT_SERVICE)
    if use_memory:
        return TraceRecorder(service=service, sink=MemorySink())
    db_path = os.environ.get("RETOBS_DB", DEFAULT_DB)
    store = SQLiteStore(db_path=db_path)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(store.init_db())
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pool.submit(asyncio.run, store.init_db()).result()
    return TraceRecorder(service=service, sink=StoreSink(store))


def create_app(use_memory: bool = False) -> FastAPI:
    app = FastAPI(title="FastAPI Search Demo")
    recorder = _build_recorder(use_memory)
    instrument_fastapi(app, recorder, pipeline_id="bm25")

    tokenized = [doc["text"].lower().split() for doc in CORPUS]
    bm25 = BM25Okapi(tokenized)

    @app.get("/search")
    async def search(q: str, request: Request, k: int = 3):
        t = get_trace(request)
        start = time.perf_counter()
        scores = bm25.get_scores(q.lower().split())
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

    return app


app = create_app(use_memory=os.environ.get("RETOBS_MEMORY_SINK") == "1")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="FastAPI search demo with TraceLens instrumentation")
    parser.add_argument("--memory", action="store_true", help="Use MemorySink instead of StoreSink")
    args = parser.parse_args()
    uvicorn.run(create_app(use_memory=args.memory), host="0.0.0.0", port=8080)
