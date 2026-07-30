"""LlamaIndex + retobs zero-touch tracing example.

Demonstrates RetobsLlamaIndexCallback: one callback line, no manual stage wrapping.

Requirements:
    pip install retrieval-observatory[llamaindex,dashboard]

Usage:
    python examples/integrations/llamaindex_search/app.py
    retobs serve --db .retobs/llamaindex_demo.db
"""
from __future__ import annotations

import asyncio
import os

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.callbacks import CallbackManager
from llama_index.core.embeddings.mock_embed_model import MockEmbedding

import retrieval_observatory as ro
from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexCallback
from retrieval_observatory.tracing.integrations.operator_registry import OperatorRegistry

# Small local corpus — no API keys needed
CORPUS_TEXTS = [
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
]

DB_PATH = ".retobs/llamaindex_demo.db"
QUERIES = [
    "What is BM25?",
    "How does dense retrieval work?",
    "What is hybrid search?",
    "Tell me about RAG systems",
    "Why do empty results happen?",
]


async def main() -> None:
    os.makedirs(".retobs", exist_ok=True)
    recorder = ro.init(service="llamaindex-demo", db=DB_PATH)
    await recorder.sink.start()

    # LlamaIndex reports the retrieval event's component_path as "retrieve".
    registry = OperatorRegistry.explicit(component_path="retrieve", op_id="retrieve", op_type="SOURCE")
    cb = RetobsLlamaIndexCallback(recorder, registry, pipeline_id="vector-store-mock")

    # Use mock embeddings — no API key needed
    Settings.embed_model = MockEmbedding(embed_dim=64)
    Settings.llm = None
    Settings.callback_manager = CallbackManager([cb])

    documents = [Document(text=text, doc_id=str(i)) for i, text in enumerate(CORPUS_TEXTS)]
    index = VectorStoreIndex.from_documents(documents)
    query_engine = index.as_query_engine(similarity_top_k=3)

    print(f"Running {len(QUERIES)} queries through LlamaIndex query engine with RetobsLlamaIndexCallback …")
    for query in QUERIES:
        response = query_engine.query(query)
        node_count = len(response.source_nodes) if hasattr(response, "source_nodes") else "?"
        print(f"  ✓ {query!r}  ({node_count} source nodes)")

    await recorder.sink.shutdown()

    print(f"\nTraces written to {DB_PATH}")
    print(f"Run: retobs serve --db {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
