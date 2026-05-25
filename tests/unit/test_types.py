from datetime import datetime

from retrieval_observatory.types import (
    BaseReranker,
    BaseRetriever,
    Document,
    PipelineResult,
    Query,
    RetrievalResult,
    StageSnapshot,
)


def test_query_defaults():
    q = Query(text="hello")
    assert q.k == 10
    assert q.query_id == ""
    assert q.temporal_anchor is None
    assert q.filters == {}


def test_document_creation():
    doc = Document(id="d1", text="hello", score=0.9, rank=1)
    assert doc.timestamp is None
    assert doc.metadata == {}


def test_pipeline_result():
    snap = StageSnapshot(stage_index=0, stage_id="r1", documents=[], latency_ms=10.0)
    result = PipelineResult(
        query_id="q1",
        pipeline_id="p1",
        snapshots=[snap],
        total_latency_ms=10.0,
        status="OK",
    )
    assert result.status == "OK"
    assert result.error_traceback is None


def test_base_retriever_protocol():
    class MockRetriever:
        retriever_id = "mock"

        def retrieve(self, query: Query) -> RetrievalResult:
            return RetrievalResult(documents=[], latency_ms=0.0, retriever_id="mock")

    assert isinstance(MockRetriever(), BaseRetriever)


def test_base_reranker_protocol():
    class MockReranker:
        retriever_id = "mock_reranker"

        def rerank(self, query, documents):
            return RetrievalResult(documents=[], latency_ms=0.0, retriever_id="mock_reranker")

    assert isinstance(MockReranker(), BaseReranker)
