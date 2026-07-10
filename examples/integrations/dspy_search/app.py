"""DSPy + retobs tracing example.

Demonstrates wrap_retrieve: wrap any retrieval callable (a dspy.Retrieve instance, or a
plain function) once, trace every subsequent call.

Requirements:
    pip install retrieval-observatory[dspy,dashboard]
    pip install dspy-ai   # only needed for the dspy.Retrieve variant, see below

Usage:
    python examples/integrations/dspy_search/app.py
    retobs serve --db .retobs/dspy_demo.db

NOTE: dspy.Retrieve requires a configured retrieval model (dspy.settings.configure(rm=...)),
which normally means pointing at a real vector index or hosted retrieval service. To keep
this example runnable offline with no external service or API key, it wraps a plain
in-memory BM25-style function instead of a real dspy.Retrieve instance -- wrap_retrieve is
duck-typed over any callable returning a list or a `.passages`-bearing object, so the exact
same wiring works unchanged for `wrap_retrieve(dspy.Retrieve(k=20), ...)` once you have a
retrieval model configured. That substitution is the only thing to change for production use.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import Counter

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.integrations.dspy import wrap_retrieve

CORPUS = {
    "d0": "BM25 is a bag-of-words retrieval function that ranks documents based on term frequency.",
    "d1": "Dense retrieval uses bi-encoder models to embed queries and documents into a shared vector space.",
    "d2": "Hybrid search combines BM25 and dense retrieval scores, often with reciprocal rank fusion.",
    "d3": "Reranking applies a cross-encoder to re-score an initial candidate set for higher precision.",
    "d4": "RAG (Retrieval-Augmented Generation) grounds LLM responses in retrieved documents.",
}
QUERIES = ["What is BM25?", "How does hybrid search work?", "What is reranking?"]
DB_PATH = ".retobs/dspy_demo.db"
RUN_ID = "dspy-demo"


def _naive_retrieve(query: str, k: int = 3) -> list[str]:
    """Stand-in for `dspy.Retrieve(k=k)(query).passages` -- plain term-overlap ranking,
    no external service or model required."""
    terms = set(query.lower().split())
    scored = Counter()
    for doc_id, text in CORPUS.items():
        scored[doc_id] = len(terms & set(text.lower().split()))
    ranked = [doc_id for doc_id, _ in scored.most_common(k)]
    return [CORPUS[doc_id] for doc_id in ranked]


async def main() -> None:
    import os

    os.makedirs(".retobs", exist_ok=True)
    store = SQLiteStore(DB_PATH)
    await store.init_db()
    await store.save_run(RUN_ID, "dspy-demo", "{}")

    retrieve = wrap_retrieve(_naive_retrieve, op_id="dspy_retrieve")

    print(f"Running {len(QUERIES)} queries through a wrapped DSPy-shaped retrieve callable …")
    for query in QUERIES:
        start_trace(ObserveContext(
            run_id=RUN_ID, query_id=f"q_{uuid.uuid4().hex[:8]}", query_text=query, pipeline_id="dspy_retrieve",
        ))
        result = retrieve(query)
        trace = finish_trace()
        await store.save_trace_v2(trace)
        print(f"  ✓ {query!r}  ({len(result)} passages, {len(trace.spans)} span(s))")

    print(f"\nTraces written to {DB_PATH}")
    print(f"Run: retobs serve --db {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
