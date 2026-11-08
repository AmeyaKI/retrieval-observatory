"""LangChain + retobs zero-touch tracing example.

Demonstrates RetobsLangChainCallback: one callback line, no manual stage wrapping.

Requirements:
    pip install retrieval-observatory[langchain,dashboard]
    pip install langchain-community faiss-cpu

Usage:
    python examples/integrations/langchain_search/app.py
    retobs serve --db .retobs/langchain_demo.db
"""
from __future__ import annotations

import asyncio
import os

from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import FakeEmbeddings
from langchain_core.runnables import RunnableLambda

import retrieval_observatory as ro
from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback
from retrieval_observatory.tracing.integrations.operator_registry import OperatorRegistry

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
    "A loss boundary marks the last operator that removed a relevant document from the candidates.",
    "Judged queries pair each question with the documents known to be relevant to it.",
    "Per-request retrieval traces record each operator's inputs and outputs.",
    "A release audit compares a baseline run with a candidate run under a declared policy.",
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
    recorder = ro.init(service="langchain-demo", db=DB_PATH)
    await recorder.sink.start()

    # LangChain doesn't pass a stable serialized component name through a piped
    # RunnableLambda chain, so the retriever span reports as component_path="retriever".
    registry = OperatorRegistry.explicit(component_path="retriever", op_id="retrieve", op_type="SOURCE")
    cb = RetobsLangChainCallback(recorder, registry, pipeline_id="faiss-fake-embed")

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
        result = chain.invoke(query, config={"callbacks": [cb]})
        print(f"  ok {query!r}  ({len(result.splitlines())} doc lines)")

    await recorder.sink.shutdown()

    print(f"\nTraces written to {DB_PATH}")
    print(f"Run: retobs serve --db {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
