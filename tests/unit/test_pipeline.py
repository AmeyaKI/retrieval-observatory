import pytest

from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.types import Document, Query, RetrievalResult


class MockRetriever:
    def __init__(self, retriever_id: str, doc_ids: list):
        self.retriever_id = retriever_id
        self._doc_ids = doc_ids

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [
            Document(id=did, text="text", score=1.0 / (i + 1), rank=i + 1)
            for i, did in enumerate(self._doc_ids[: query.k])
        ]
        return RetrievalResult(documents=docs, latency_ms=5.0, retriever_id=self.retriever_id)


class MockReranker:
    def __init__(self, retriever_id: str):
        self.retriever_id = retriever_id

    def rerank(self, query: Query, documents: list) -> RetrievalResult:
        # Reverse order to simulate reranking
        reranked = [
            Document(id=d.id, text=d.text, score=1.0 / (i + 1), rank=i + 1)
            for i, d in enumerate(reversed(documents[: query.k]))
        ]
        return RetrievalResult(documents=reranked, latency_ms=3.0, retriever_id=self.retriever_id)


@pytest.mark.asyncio
async def test_single_stage_pipeline():
    retriever = MockRetriever("r1", ["d1", "d2", "d3"])
    pipeline = SingleStagePipeline(pipeline_id="p1", retriever=retriever)

    query = Query(text="test", k=3, query_id="q1")
    result = await pipeline.run(query)

    assert result.status == "OK"
    assert result.query_id == "q1"
    assert result.pipeline_id == "p1"
    assert len(result.snapshots) == 1
    assert len(result.snapshots[0].documents) == 3
    assert result.total_latency_ms == 5.0


@pytest.mark.asyncio
async def test_multi_stage_pipeline():
    retriever = MockRetriever("r1", ["d1", "d2", "d3", "d4", "d5"])
    reranker = MockReranker("reranker1")
    pipeline = MultiStagePipeline(
        pipeline_id="p_multi",
        stages=[retriever, reranker],
        k_per_stage=[5, 3],
    )

    query = Query(text="test", k=3, query_id="q1")
    result = await pipeline.run(query)

    assert result.status == "OK"
    assert len(result.snapshots) == 2
    assert result.snapshots[0].stage_index == 0
    assert result.snapshots[1].stage_index == 1
    assert len(result.snapshots[1].documents) == 3


@pytest.mark.asyncio
async def test_single_stage_error_handling():
    class FailingRetriever:
        retriever_id = "failing"

        def retrieve(self, query):
            raise RuntimeError("Network error")

    pipeline = SingleStagePipeline(pipeline_id="p_fail", retriever=FailingRetriever())
    result = await pipeline.run(Query(text="test", query_id="q1"))

    assert result.status == "ERROR"
    assert result.error_traceback is not None
    assert "RuntimeError" in result.error_traceback


@pytest.mark.asyncio
async def test_multi_stage_preserves_completed_stages_on_error():
    retriever = MockRetriever("r1", ["d1", "d2"])

    class FailingReranker:
        retriever_id = "failing_reranker"

        def rerank(self, query, documents):
            raise RuntimeError("API error")

    pipeline = MultiStagePipeline(
        pipeline_id="p_multi_fail",
        stages=[retriever, FailingReranker()],
        k_per_stage=[2, 1],
    )
    result = await pipeline.run(Query(text="test", query_id="q1"))

    assert result.status == "ERROR"
    # Stage 0 completed before failure
    assert len(result.snapshots) == 1
    assert result.snapshots[0].stage_id == "r1"
