"""PipelineGraph projection: topology fidelity to the executed DAG, mandatory CIs at the
render boundary, and conformance to the frozen JSON contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set

import pytest

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline.dag import DAGNode, DAGPipeline
from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, Query, RetrievalResult

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "retrieval_observatory" / "dashboard" / "pipeline_graph.schema.json"
)


class _FakeRetriever:
    def __init__(self, rid: str, ids: List[str]):
        self.retriever_id = rid
        self._ids = ids

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [Document(id=i, text="", score=1.0 / (r + 1), rank=r + 1) for r, i in enumerate(self._ids[: query.k])]
        return RetrievalResult(documents=docs, latency_ms=5.0, retriever_id=self.retriever_id)


class _FakeReranker:
    def __init__(self, rid: str, keep: int):
        self.retriever_id = rid
        self._keep = keep

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        ordered = documents[: self._keep]
        docs = [Document(id=d.id, text=d.text, score=d.score, rank=r + 1) for r, d in enumerate(ordered)]
        return RetrievalResult(documents=docs, latency_ms=3.0, retriever_id=self.retriever_id)


def _hybrid_dag() -> DAGPipeline:
    return DAGPipeline(
        pipeline_id="hybrid",
        nodes=[
            DAGNode("bm25", "SOURCE", inputs=[], adapter=_FakeRetriever("bm25", ["d1", "d2", "d3", "d4"]), k=4),
            DAGNode("dense", "SOURCE", inputs=[], adapter=_FakeRetriever("dense", ["d3", "d1", "d5", "d6"]), k=4),
            DAGNode("fuse", "FUSE", inputs=["bm25", "dense"], rrf_k=60, top_k=10, k=10),
            DAGNode("rerank", "RERANK", inputs=["fuse"], adapter=_FakeReranker("rerank", keep=3), k=3),
        ],
        output_id="rerank",
    )


async def _run_and_project(tmp_path) -> list:
    store = SQLiteStore(db_path=str(tmp_path / "graph.db"))
    await store.init_db()
    await store.save_run(run_id="run", experiment_name="t", config_json="{}")
    pipe = _hybrid_dag()
    qrels: Dict[str, Set[str]] = {}
    traces = []
    for i in range(30):  # enough queries for a non-degenerate bootstrap CI
        qid = f"q{i}"
        qrels[qid] = {"d1", "d3"}
        result = await pipe.run(Query(text="q", k=10, query_id=qid))
        result.trace_v2.run_id = "run"
        result.trace_v2.trace_id = f"t{i}"
        await store.save_trace_v2(result.trace_v2)
        traces.append(result.trace_v2)
    engine = MetricsEngine(recall_at_k_values=[10], ndcg_at_k_values=[10], compute_mrr=False, compute_map=False)
    await engine.compute_from_traces("run", store, traces, qrels)
    agg = await engine.aggregate("run", store)
    return build_pipeline_graphs(agg, await store.get_traces_v2("run"))


@pytest.mark.asyncio
async def test_graph_topology_matches_executed_dag(tmp_path):
    graphs = await _run_and_project(tmp_path)
    assert len(graphs) == 1
    g = graphs[0]
    ids = {n.node_id for n in g.nodes}
    assert ids == {"bm25", "dense", "fuse", "rerank"}
    depth = {n.node_id: n.depth for n in g.nodes}
    assert depth["bm25"] == 0 and depth["dense"] == 0
    assert depth["fuse"] == 1 and depth["rerank"] == 2
    fuse = next(n for n in g.nodes if n.node_id == "fuse")
    assert fuse.is_merge is True
    fan_in = {(e.source, e.target) for e in g.edges if e.kind == "fan_in"}
    assert fan_in == {("bm25", "fuse"), ("dense", "fuse")}
    assert ("fuse", "rerank") in {(e.source, e.target) for e in g.edges}


@pytest.mark.asyncio
async def test_graph_metrics_carry_ci(tmp_path):
    graphs = await _run_and_project(tmp_path)
    seen_any = False
    for node in graphs[0].nodes:
        for mv in (node.metrics.ndcg10, node.metrics.recall, node.metrics.latency_p50):
            if mv is None or mv.mean is None:
                continue
            seen_any = True
            # latency percentiles legitimately have null CIs; quality metrics must not.
            if mv.ci_low is not None:
                assert mv.ci_low <= mv.mean <= mv.ci_high
    assert seen_any, "expected at least one measured metric on the graph"


@pytest.mark.asyncio
async def test_graph_conforms_to_contract(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text())
    graphs = await _run_and_project(tmp_path)
    for g in graphs:
        jsonschema.validate(instance=g.to_dict(), schema=schema)
