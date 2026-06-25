"""LangChain + retobs zero-touch tracing example.

Demonstrates RetobsLangChainCallback: one callback line, no manual stage wrapping.

Requirements:
    pip install retrieval-observatory[langchain,dashboard]
    pip install langchain-community faiss-cpu

Usage:
    python examples/langchain_search/app.py
    retobs serve --db .retobs/langchain_demo.db
"""
from __future__ import annotations

import asyncio
import os

from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import FakeEmbeddings
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback
from retrieval_observatory.tracing.recorder import TraceRecorder
from retrieval_observatory.tracing.sink import StoreSink
from retrieval_observatory.store.sqlite import SQLiteStore

# Small local corpus — no API keys needed
CORPUS = [
    "BM25 is a bag-of-words retrieval function that ranks documents based on term frequency.",
    "Dense retrieval uses bi-encoder models to embed queries and documents into a shared vector space.",
    "Hybrid search combines BM25 and dense retrieval scores, often with reciprocal rank fusion.",
    "Reranking applies a cross-encoder to re-score an initial candidate set for higher precision.",
    "RAG (Retrieval-Augmented Generation) grounds LLM responses in retrieved documents.",
    "Latency budgets are critical in production RAG — p99 latency matters as much as recall.",
    "BEIR is a heterogeneous benchmark suite for evaluating zero-shot retrieval across domains.",
    "Multi-query retrieval generates multiple query variants to improve recall at the cost of latency.",
    "Reciprocal rank fusion (RRF) is a simple score combination method that works without learning.",
    "Empty result sets are a common failure mode: the retriever returns no candidates for rare queries.",
    "Candidate churn measures how much the document set changes between pipeline stages.",
    "Query difficulty classification helps predict which queries a pipeline will struggle with.",
    "Forge generates corpus-specific stress-test queries targeting known retrieval failure scenarios.",
    "TraceLens captures per-request retrieval traces to diagnose production reliability issues.",
    "The Advisor compares benchmark runs and surfaces statistically significant regressions.",
]

DB_PATH = ".retobs/langchain_demo.db"
QUERIES = [
    "What is BM25?",
    "How does dense retrieval work?",
    "What is hybrid search?",
    "Tell me about RAG systems",
    "Why do empty results happen?",
]


async def main() -> None:
    os.makedirs(".retobs", exist_ok=True)
    store = SQLiteStore(DB_PATH)
    await store.init_db()

    sink = StoreSink(store, latency_budget_ms=500.0)
    recorder = TraceRecorder(service="langchain-demo", sink=sink)
    cb = RetobsLangChainCallback(recorder, pipeline_id="faiss-fake-embed")

    # Build a FAISS vectorstore with deterministic fake embeddings (no API key)
    embeddings = FakeEmbeddings(size=64)
    vectorstore = FAISS.from_texts(CORPUS, embedding=embeddings)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # Minimal chain: retrieve → format as text (no LLM required, no API keys needed)
    def format_docs(docs):
        return "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(docs))

    chain = retriever | RunnableLambda(format_docs)

    print(f"Running {len(QUERIES)} queries through LangChain chain with RetobsLangChainCallback …")
    for query in QUERIES:
        try:
            result = chain.invoke(query, config={"callbacks": [cb]})
            print(f"  ✓ {query!r}  ({len(result.splitlines())} doc lines)")
        except Exception as exc:
            print(f"  ✗ {query!r}: {exc}")

    # Yield to the event loop so fire-and-forget flush tasks complete
    await asyncio.sleep(0.1)

    print(f"\nTraces written to {DB_PATH}")
    print(f"Run: retobs serve --db {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
