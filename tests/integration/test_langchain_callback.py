"""Integration tests for RetobsLangChainCallback.

Requires: pip install retrieval-observatory[langchain]
          pip install langchain-community faiss-cpu
"""
import asyncio
import pytest

langchain_core = pytest.importorskip("langchain_core")
langchain_community = pytest.importorskip("langchain_community")

from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import FakeEmbeddings
from langchain_core.runnables import RunnableLambda

from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback
from retrieval_observatory.tracing.recorder import TraceRecorder
from retrieval_observatory.tracing.sink import MemorySink


CORPUS = [
    "BM25 ranks documents using term frequency and inverse document frequency.",
    "Dense retrieval encodes queries and documents with bi-encoder neural networks.",
    "Hybrid search combines sparse and dense retrieval with reciprocal rank fusion.",
    "Reranking uses cross-encoders to re-score a candidate set for higher precision.",
    "RAG grounds LLM responses in retrieved documents to reduce hallucinations.",
    "Empty result sets occur when no documents match the retrieval query.",
    "Latency budgets determine the maximum acceptable retrieval time in production.",
    "Multi-query retrieval generates multiple query variants to improve recall.",
]

QUERIES = [
    "What is BM25?",
    "How does dense retrieval work?",
    "What is hybrid search?",
    "Tell me about RAG",
    "Why do empty results happen?",
]


def _make_chain(corpus=None):
    embeddings = FakeEmbeddings(size=32)
    texts = corpus or CORPUS
    vs = FAISS.from_texts(texts, embedding=embeddings)
    retriever = vs.as_retriever(search_kwargs={"k": 3})
    return retriever | RunnableLambda(lambda docs: [d.page_content for d in docs])


def test_five_queries_produce_five_traces():
    """Each chain.invoke call should produce exactly one trace in the sink."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-lc", sink=sink)
    cb = RetobsLangChainCallback(recorder, pipeline_id="faiss-test")
    chain = _make_chain()

    for query in QUERIES:
        result = chain.invoke(query, config={"callbacks": [cb]})
        assert isinstance(result, list)

    # finish_trace_sync schedules tasks; run them
    asyncio.run(asyncio.sleep(0.1))
    assert len(sink.traces) == len(QUERIES)


def test_each_trace_has_one_stage_and_positive_latency():
    """Each trace should have exactly one retriever stage with latency > 0."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-lc", sink=sink)
    cb = RetobsLangChainCallback(recorder, pipeline_id="faiss-test")
    chain = _make_chain()

    chain.invoke(QUERIES[0], config={"callbacks": [cb]})
    asyncio.run(asyncio.sleep(0.1))

    assert len(sink.traces) == 1
    trace = sink.traces[0]
    assert len(trace.snapshots) == 1
    assert trace.snapshots[0].latency_ms > 0
    assert trace.total_latency_ms > 0
    assert len(trace.final_results) > 0


def test_query_text_captured():
    """The trace must capture the query text that was sent to the chain."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-lc", sink=sink)
    cb = RetobsLangChainCallback(recorder, pipeline_id="faiss-test")
    chain = _make_chain()

    query = "What is BM25?"
    chain.invoke(query, config={"callbacks": [cb]})
    asyncio.run(asyncio.sleep(0.1))

    assert len(sink.traces) == 1
    assert sink.traces[0].query_text == query


def test_multi_retriever_no_double_counting():
    """Two separate chain.invoke calls should produce exactly two traces (not four)."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-lc", sink=sink)
    cb = RetobsLangChainCallback(recorder, pipeline_id="faiss-test")
    chain = _make_chain()

    chain.invoke("query one", config={"callbacks": [cb]})
    chain.invoke("query two", config={"callbacks": [cb]})
    asyncio.run(asyncio.sleep(0.1))

    assert len(sink.traces) == 2
    for trace in sink.traces:
        # Each trace should have exactly one retriever stage, not duplicated
        assert len(trace.snapshots) == 1


def test_pipeline_id_propagated():
    """The pipeline_id passed to the callback should appear on the trace."""
    sink = MemorySink()
    recorder = TraceRecorder(service="test-lc", sink=sink)
    pipeline_id = "my-faiss-pipeline"
    cb = RetobsLangChainCallback(recorder, pipeline_id=pipeline_id)
    chain = _make_chain()

    chain.invoke("test", config={"callbacks": [cb]})
    asyncio.run(asyncio.sleep(0.1))

    assert len(sink.traces) == 1
    assert sink.traces[0].pipeline_id == pipeline_id
