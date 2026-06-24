"""Integration tests for RetobsLlamaIndexCallback.

Requires: pip install retobs[llamaindex]
"""
import asyncio
import pytest

llama_index_core = pytest.importorskip("llama_index.core")

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.callbacks import CallbackManager
from llama_index.core.embeddings.mock_embed_model import MockEmbedding

from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexCallback
from retrieval_observatory.tracing.recorder import TraceRecorder
from retrieval_observatory.tracing.sink import MemorySink


CORPUS = [
    "BM25 ranks documents using term frequency and inverse document frequency.",
    "Dense retrieval encodes queries and documents with bi-encoder neural networks.",
    "Hybrid search combines sparse and dense retrieval using reciprocal rank fusion.",
    "Reranking uses cross-encoders to re-score a candidate set for higher precision.",
    "RAG grounds LLM responses in retrieved documents to reduce hallucinations.",
]

QUERIES = [
    "What is BM25?",
    "How does dense retrieval work?",
    "What is hybrid search?",
    "Tell me about RAG",
    "Why do empty results happen?",
]


@pytest.fixture(autouse=True)
def li_settings():
    Settings.embed_model = MockEmbedding(embed_dim=32)
    Settings.llm = None
    yield
    Settings.embed_model = None
    Settings.llm = None
    Settings.callback_manager = CallbackManager([])


def _make_query_engine(cb: RetobsLlamaIndexCallback, top_k: int = 3):
    Settings.callback_manager = CallbackManager([cb])
    docs = [Document(text=text, doc_id=str(i)) for i, text in enumerate(CORPUS)]
    index = VectorStoreIndex.from_documents(docs)
    return index.as_query_engine(similarity_top_k=top_k)


def test_five_queries_produce_five_traces():
    """Each query_engine.query call should produce exactly one trace."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-li", sink=sink)
    cb = RetobsLlamaIndexCallback(recorder, pipeline_id="li-test")
    qe = _make_query_engine(cb)

    for query in QUERIES:
        qe.query(query)

    asyncio.run(asyncio.sleep(0.1))
    assert len(sink.traces) == len(QUERIES)


def test_each_trace_has_retrieve_stage():
    """Each trace should contain at least one retriever stage with positive latency."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-li", sink=sink)
    cb = RetobsLlamaIndexCallback(recorder, pipeline_id="li-test")
    qe = _make_query_engine(cb)

    qe.query("What is BM25?")
    asyncio.run(asyncio.sleep(0.1))

    assert len(sink.traces) == 1
    trace = sink.traces[0]
    assert len(trace.snapshots) >= 1
    assert trace.snapshots[0].stage_id == "retriever"
    assert trace.snapshots[0].latency_ms > 0
    assert len(trace.final_results) > 0


def test_pipeline_id_propagated():
    """The pipeline_id should appear on the trace."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-li", sink=sink)
    cb = RetobsLlamaIndexCallback(recorder, pipeline_id="my-li-pipeline")
    qe = _make_query_engine(cb)

    qe.query("test query")
    asyncio.run(asyncio.sleep(0.1))

    assert len(sink.traces) == 1
    assert sink.traces[0].pipeline_id == "my-li-pipeline"


def test_retrieved_nodes_become_documents():
    """Nodes returned by the retriever should become Document objects in the snapshot."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-li", sink=sink)
    cb = RetobsLlamaIndexCallback(recorder, pipeline_id="li-test")
    qe = _make_query_engine(cb, top_k=2)

    qe.query("What is BM25?")
    asyncio.run(asyncio.sleep(0.1))

    trace = sink.traces[0]
    snapshot = trace.snapshots[0]
    assert len(snapshot.documents) == 2
    assert all(doc.text for doc in snapshot.documents)
    assert all(doc.rank > 0 for doc in snapshot.documents)
