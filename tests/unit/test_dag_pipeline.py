"""DAG pipeline executor: topology fidelity, trace parent_ids, and depth-based metric
bucketing for a genuine hybrid fan-in (parallel sources → RRF fuse → rerank)."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set

import pytest

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline.dag import DAGNode, DAGPipeline
from retrieval_observatory.types import Document, Query, RetrievalResult


class _FakeRetriever:
    def __init__(self, retriever_id: str, ranked_ids: List[str]):
        self.retriever_id = retriever_id
        self._ids = ranked_ids

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [Document(id=i, text="", score=1.0 / (r + 1), rank=r + 1) for r, i in enumerate(self._ids[: query.k])]
        return RetrievalResult(documents=docs, latency_ms=5.0, retriever_id=self.retriever_id)


class _FakeReranker:
    def __init__(self, retriever_id: str, keep: int):
        self.retriever_id = retriever_id
        self._keep = keep

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        # Reverse order to make the effect observable, keep top-N.
        ordered = list(reversed(documents))[: self._keep]
        docs = [Document(id=d.id, text=d.text, score=d.score, rank=r + 1) for r, d in enumerate(ordered)]
        return RetrievalResult(documents=docs, latency_ms=3.0, retriever_id=self.retriever_id)


def _hybrid_dag() -> DAGPipeline:
    return DAGPipeline(
        pipeline_id="hybrid",
        nodes=[
            DAGNode("bm25", "SOURCE", inputs=[], adapter=_FakeRetriever("bm25", ["d1", "d2", "d3", "d4"]), k=4),
            DAGNode("dense", "SOURCE", inputs=[], adapter=_FakeRetriever("dense", ["d3", "d5", "d1", "d6"]), k=4),
            DAGNode("fuse", "FUSE", inputs=["bm25", "dense"], rrf_k=60, top_k=10, k=10),
            DAGNode("rerank", "RERANK", inputs=["fuse"], adapter=_FakeReranker("rerank", keep=3), k=3),
        ],
        output_id="rerank",
    )


@pytest.mark.asyncio
async def test_dag_emits_branching_trace():
    result = await _hybrid_dag().run(Query(text="q", k=10, query_id="q1"))
    assert result.status == "OK"
    trace = result.trace_v2
    assert trace is not None
    spans = {s.op_id: s for s in trace.spans}
    assert set(spans) == {"bm25", "dense", "fuse", "rerank"}
    # Real fan-in: fuse has two parents; sources have none; rerank has one.
    assert spans["bm25"].parent_ids == []
    assert spans["dense"].parent_ids == []
    assert sorted(spans["fuse"].parent_ids) == ["bm25", "dense"]
    assert spans["rerank"].parent_ids == ["fuse"]
    assert trace.final_op_id == "rerank"


@pytest.mark.asyncio
async def test_dag_metric_depths_and_branches():
    engine = MetricsEngine(recall_at_k_values=[3], ndcg_at_k_values=[10], compute_mrr=False, compute_map=False)
    result = await _hybrid_dag().run(Query(text="q", k=10, query_id="q1"))
    qrels: Dict[str, Set[str]] = {"q1": {"d1", "d3"}}

    rows: List[Dict] = []

    class _Store:
        async def save_metrics_batch(self, r):
            rows.extend(r)

        async def get_metrics(self, run_id):
            return []

        async def get_run_status_counts(self, run_id):
            return {}

    await engine.compute_from_traces("run", _Store(), [result.trace_v2], qrels)

    # Depth: sources at 0 (parallel → branch_id set), fuse at 1, rerank at 2 (spine → None).
    by_key = defaultdict(list)
    for r in rows:
        if r["metric_name"] == "recall":
            by_key[(r["stage_index"], r.get("branch_id"))].append(r)
    assert (0, "bm25") in by_key
    assert (0, "dense") in by_key
    assert (1, None) in by_key  # fuse is the sole node at depth 1
    assert (2, None) in by_key  # rerank spine
    # No parallel source landed on the spine key (0, None).
    assert (0, None) not in by_key
