from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from retrieval_observatory.runner.cache import StageResultCache, _make_stage_cache_key, _snap_from_json, _snap_to_json
from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.types import Document, Query, RetrievalResult, StageSnapshot


class MockRetriever:
    def __init__(self, retriever_id: str, call_count_ref: list | None = None):
        self.retriever_id = retriever_id
        self._call_count_ref = call_count_ref if call_count_ref is not None else []

    def retrieve(self, query: Query) -> RetrievalResult:
        self._call_count_ref.append(1)
        docs = [Document(id=f"d{i}", text=f"text{i}", score=1.0 / (i + 1), rank=i + 1) for i in range(query.k)]
        return RetrievalResult(documents=docs, latency_ms=10.0, retriever_id=self.retriever_id)


class MockReranker:
    def __init__(self, retriever_id: str, call_count_ref: list | None = None):
        self.retriever_id = retriever_id
        self._call_count_ref = call_count_ref if call_count_ref is not None else []

    def rerank(self, query: Query, documents: list) -> RetrievalResult:
        self._call_count_ref.append(1)
        return RetrievalResult(documents=documents[: query.k], latency_ms=5.0, retriever_id=self.retriever_id)


def test_stage_cache_key_is_stable():
    key1 = _make_stage_cache_key("stage_yaml", "q1")
    key2 = _make_stage_cache_key("stage_yaml", "q1")
    assert key1 == key2

    # Different query → different key
    key3 = _make_stage_cache_key("stage_yaml", "q2")
    assert key1 != key3

    # Different stage config → different key
    key4 = _make_stage_cache_key("other_yaml", "q1")
    assert key1 != key4


def test_stage_cache_shared_across_pipelines():
    """Same stage config embedded in two different pipelines should produce the same cache key."""
    cache = StageResultCache(store=MagicMock())
    bm25_stage_cfg = {"type": "adapter.bm25", "config": {"k": 100}}

    # Same stage config → same key regardless of which pipeline uses it
    key_from_pipeline_a = cache.key_for(bm25_stage_cfg, "q42")
    key_from_pipeline_b = cache.key_for(bm25_stage_cfg, "q42")
    assert key_from_pipeline_a == key_from_pipeline_b

    # Different stage config → different key
    different_stage_cfg = {"type": "adapter.bm25", "config": {"k": 50}}
    key_different = cache.key_for(different_stage_cfg, "q42")
    assert key_from_pipeline_a != key_different


def test_stage_cache_key_differs_by_upstream_candidates():
    cache = StageResultCache(store=MagicMock())
    reranker_cfg = {"type": "adapter.hf_crossencoder", "config": {"k": 10, "model": "ce-model"}}

    key_bm25_upstream = cache.key_for(reranker_cfg, "q1", upstream_doc_ids=["d1", "d2", "d3"])
    key_dense_upstream = cache.key_for(reranker_cfg, "q1", upstream_doc_ids=["d9", "d8", "d7"])
    assert key_bm25_upstream != key_dense_upstream


def test_stage_cache_key_same_upstream_candidates():
    cache = StageResultCache(store=MagicMock())
    reranker_cfg = {"type": "adapter.hf_crossencoder", "config": {"k": 10, "model": "ce-model"}}
    upstream = ["d3", "d1", "d2"]

    key_a = cache.key_for(reranker_cfg, "q1", upstream_doc_ids=upstream)
    key_b = cache.key_for(reranker_cfg, "q1", upstream_doc_ids=["d2", "d3", "d1"])
    assert key_a == key_b


@pytest.mark.asyncio
async def test_multistage_uses_stage_cache():
    """Second run should use cached stage 0 output; retriever should only be called once."""
    retriever_calls: list = []
    retriever = MockRetriever("bm25", call_count_ref=retriever_calls)
    reranker = MockReranker("cross-encoder")

    stage_cfgs = [
        {"type": "adapter.bm25", "config": {"k": 10}},
        {"type": "adapter.hf_crossencoder", "config": {"k": 5, "model": "ce-model"}},
    ]

    # Use an in-memory store mock that actually stores and retrieves data
    _store: dict = {}

    mock_store = MagicMock()
    mock_store.cache_get = AsyncMock(side_effect=lambda key: _store.get(key))
    mock_store.cache_set = AsyncMock(side_effect=lambda key, val: _store.__setitem__(key, val))

    stage_cache = StageResultCache(store=mock_store)

    pipeline = MultiStagePipeline(
        pipeline_id="bm25__cross_encoder",
        stages=[retriever, reranker],
        k_per_stage=[10, 5],
        stage_configs=stage_cfgs,
        stage_cache=stage_cache,
    )

    query = Query(text="what is retrieval?", k=5, query_id="q1")

    # First run: retriever must execute
    result1 = await pipeline.run(query)
    assert result1.status == "OK"
    assert len(retriever_calls) == 1

    # Second run: retriever stage should be served from cache
    result2 = await pipeline.run(query)
    assert result2.status == "OK"
    assert len(retriever_calls) == 1  # still 1 — retriever was NOT called again
    assert len(result2.snapshots) == 2


def test_cache_roundtrip_with_arms():
    snap = StageSnapshot(
        stage_index=0,
        stage_id="hybrid_fused",
        documents=[Document(id="f1", text="fused", score=1.0, rank=1)],
        latency_ms=9.0,
        candidate_count=1,
        arms=[
            StageSnapshot(
                stage_index=0,
                stage_id="bm25_arm",
                documents=[Document(id="a1", text="arm", score=0.7, rank=1)],
                latency_ms=4.0,
                candidate_count=1,
            )
        ],
    )

    encoded = _snap_to_json(snap)
    decoded = _snap_from_json(encoded)

    assert decoded.stage_id == "hybrid_fused"
    assert len(decoded.arms) == 1
    assert decoded.arms[0].stage_id == "bm25_arm"
    assert decoded.arms[0].documents[0].id == "a1"
