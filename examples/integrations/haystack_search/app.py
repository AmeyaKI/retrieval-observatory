"""Haystack + retobs tracing example.

Demonstrates wrap_haystack_component: wrap a retriever once, trace every subsequent call.

Requirements:
    pip install retrieval-observatory[haystack,dashboard]
    pip install haystack-ai

Usage:
    python examples/integrations/haystack_search/app.py
    retobs serve --db .retobs/haystack_demo.db

NOTE: this example was written against Haystack 2.x's InMemoryDocumentStore /
InMemoryBM25Retriever API and could not be executed against the real `haystack-ai`
package in the environment this was authored in (no network access to install it). The
tracing wrapper itself (`wrap_haystack_component`) is fully unit-tested against stub
components in tests/unit/test_framework_adapters.py without needing Haystack installed.
If Haystack's API has since changed, only the `haystack.Document`/`InMemoryDocumentStore`/
`InMemoryBM25Retriever` lines below need adjusting -- the retobs wiring stays the same.
"""
from __future__ import annotations

import asyncio
import uuid

from haystack import Document
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
from haystack.document_stores.in_memory import InMemoryDocumentStore

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.integrations.haystack import wrap_haystack_component

# Small local corpus — no API keys needed
CORPUS = [
    "BM25 is a bag-of-words retrieval function that ranks documents based on term frequency.",
    "Dense retrieval uses bi-encoder models to embed queries and documents into a shared vector space.",
    "Hybrid search combines BM25 and dense retrieval scores, often with reciprocal rank fusion.",
    "Reranking applies a cross-encoder to re-score an initial candidate set for higher precision.",
    "RAG (Retrieval-Augmented Generation) grounds LLM responses in retrieved documents.",
]

QUERIES = ["What is BM25?", "How does hybrid search work?", "What is reranking?"]
DB_PATH = ".retobs/haystack_demo.db"
RUN_ID = "haystack-demo"


async def main() -> None:
    import os

    os.makedirs(".retobs", exist_ok=True)
    store = SQLiteStore(DB_PATH)
    await store.init_db()
    await store.save_run(RUN_ID, "haystack-demo", "{}")

    doc_store = InMemoryDocumentStore()
    doc_store.write_documents([Document(content=text, id=f"d{i}") for i, text in enumerate(CORPUS)])
    retriever = InMemoryBM25Retriever(document_store=doc_store)

    # Wrap once, in place -- BM25 over a fixed corpus is exact/reproducible.
    wrap_haystack_component(
        retriever, op_type="SOURCE", op_id="bm25",
        deterministic=True, replay_policy="EXACT",
    )

    print(f"Running {len(QUERIES)} queries through a wrapped Haystack BM25 retriever …")
    for query in QUERIES:
        start_trace(ObserveContext(
            run_id=RUN_ID, query_id=f"q_{uuid.uuid4().hex[:8]}", query_text=query, pipeline_id="haystack_bm25",
        ))
        result = retriever.run(query=query)
        trace = finish_trace()
        await store.save_trace_v2(trace)
        print(f"  ✓ {query!r}  ({len(result['documents'])} docs, {len(trace.spans)} span(s))")

    print(f"\nTraces written to {DB_PATH}")
    print(f"Run: retobs serve --db {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
