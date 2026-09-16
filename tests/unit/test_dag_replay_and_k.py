"""DAG execution evidence: replay tiers on every span, each node's configured k actually applied,
executor-side truncation recorded as such, and duplicate adapter outputs survived."""
from __future__ import annotations

import pytest

from retrieval_observatory.config.operators import PipelineGraphSpec, RerankSpec, SourceSpec
from retrieval_observatory.config.schema import GraphPipelineConfig
from retrieval_observatory.pipeline.dag import DEFAULT_REPLAY_POLICY, DAGNode, DAGPipeline
from retrieval_observatory.pipeline.executors import OperatorConfigurationError
from retrieval_observatory.pipeline.factory import build_dag_from_config
from retrieval_observatory.types import Document, Query, RetrievalResult


class _Retriever:
    """Returns ``query.k`` documents and remembers every k it was asked for."""

    def __init__(self, retriever_id: str, order: list[str]):
        self.retriever_id = retriever_id
        self._order = order
        self.seen_k: list[int] = []

    def retrieve(self, query: Query) -> RetrievalResult:
        self.seen_k.append(query.k)
        docs = [Document(id=i, text="", score=1.0 / (r + 1), rank=r + 1) for r, i in enumerate(self._order[: query.k])]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id=self.retriever_id)


class _Reranker:
    """A faithful reranker: scores everything it is given and returns it all, reversed."""

    def __init__(self):
        self.seen_k: list[int] = []

    def rerank(self, query: Query, documents: list[Document]) -> RetrievalResult:
        self.seen_k.append(query.k)
        docs = [Document(id=d.id, text=d.text, score=1.0, rank=r) for r, d in enumerate(reversed(documents), 1)]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id="rr")


class _MockPostProcessor:
    retriever_id = "post"

    def rerank(self, query: Query, documents: list[Document]) -> RetrievalResult:
        docs = [Document(id=d.id, text=d.text, score=1.0, rank=r) for r, d in enumerate(documents, 1)]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id="post")


def build_post_processor(corpus, stage_cfg):
    return _MockPostProcessor(), int(stage_cfg.get("config", {}).get("k", 10))


def _hybrid() -> tuple[DAGPipeline, _Retriever, _Retriever]:
    ids = [f"d{i}" for i in range(1, 41)]
    a, b = _Retriever("a", ids), _Retriever("b", list(reversed(ids)))
    pipeline = DAGPipeline(
        pipeline_id="hybrid",
        nodes=[
            DAGNode("a", "SOURCE", adapter=a, k=30),
            DAGNode("b", "SOURCE", adapter=b, k=30),
            DAGNode("fuse", "FUSE", inputs=["a", "b"], top_k=25),
            DAGNode("rerank", "RERANK", inputs=["fuse"], adapter=_Reranker(), k=5),
        ],
        output_id="rerank",
    )
    return pipeline, a, b


def test_default_replay_policy_table_is_exposed():
    assert DEFAULT_REPLAY_POLICY["FUSE"] == "EXACT"
    assert DEFAULT_REPLAY_POLICY["FILTER"] == "EXACT"
    assert DEFAULT_REPLAY_POLICY["BOOST"] == "EXACT"
    assert DEFAULT_REPLAY_POLICY["RERANK"] == "OBSERVED_ABLATION"
    assert DEFAULT_REPLAY_POLICY["EXPAND"] == "OBSERVED_ABLATION"
    assert DEFAULT_REPLAY_POLICY["GATE"] == "OBSERVED_ABLATION"
    assert DEFAULT_REPLAY_POLICY["TRANSFORM"] == "OBSERVED_ABLATION"
    assert DEFAULT_REPLAY_POLICY["GENERATE"] == "NOT_REPLAYABLE"
    assert DEFAULT_REPLAY_POLICY["SOURCE"] == "NOT_REPLAYABLE"


@pytest.mark.asyncio
async def test_dag_spans_carry_replay_tiers():
    pipeline, _, _ = _hybrid()
    result = await pipeline.run(Query(text="q", k=10, query_id="q1"))
    spans = {s.op_id: s for s in result.trace.spans}

    # Sources consumed by a FUSE can be replayed exactly from their recorded outputs.
    assert spans["a"].replay_policy == "EXACT"
    assert spans["b"].replay_policy == "EXACT"
    assert spans["fuse"].replay_policy == "EXACT"
    assert spans["fuse"].deterministic is True
    assert spans["rerank"].replay_policy == "OBSERVED_ABLATION"
    assert spans["rerank"].deterministic is False


@pytest.mark.asyncio
async def test_source_without_a_fuse_child_is_not_replayable_and_params_override():
    src = _Retriever("src", ["d1", "d2"])
    graph = PipelineGraphSpec("p", (
        SourceSpec("src", (), adapter="src"),
        RerankSpec("rr", ("src",), params={"replay_policy": "EXACT", "deterministic": True}, adapter="rr", top_k=5),
    ), ("rr",))
    result = await DAGPipeline(graph, {"src": src, "rr": _Reranker()}).run(Query(text="q", query_id="q"))
    spans = {s.op_id: s for s in result.trace.spans}

    assert spans["src"].replay_policy == "NOT_REPLAYABLE"
    assert spans["rr"].replay_policy == "EXACT"
    assert spans["rr"].deterministic is True

    bad = PipelineGraphSpec("p", (SourceSpec("src", (), params={"replay_policy": "SOMETIMES"}, adapter="src"),), ("src",))
    with pytest.raises(OperatorConfigurationError, match="replay_policy"):
        DAGPipeline(bad, {"src": src})


@pytest.mark.asyncio
async def test_node_k_is_applied_over_query_k():
    """A source's configured k and a fuse's top_k win over the incoming query.k."""
    pipeline, a, b = _hybrid()
    result = await pipeline.run(Query(text="q", k=10, query_id="q1"))
    spans = {s.op_id: s for s in result.trace.spans}

    assert a.seen_k == [30] and b.seen_k == [30]
    assert len(spans["a"].outputs) == 30
    assert spans["a"].params["k"] == 30
    assert len(spans["fuse"].outputs) == 25
    assert spans["fuse"].params["top_k"] == 25
    fused_out = [c for group in spans["fuse"].input_groups.values() for c in group if c.output_rank is None]
    assert fused_out and {c.drop_reason for c in fused_out} == {"truncated"}
    assert {c.decision_evidence for c in fused_out} == {"recorded"}


@pytest.mark.asyncio
async def test_graph_config_k_is_applied_by_bm25_sources():
    corpus = {f"d{i}": f"alpha beta gamma doc{i} " + ("common " * (i % 5)) for i in range(40)}
    graph = GraphPipelineConfig.model_validate({
        "id": "g",
        "nodes": [
            {"id": "bm25_a", "type": "adapter.bm25", "config": {"k": 30}},
            {"id": "bm25_b", "type": "adapter.bm25", "config": {"k": 30, "tokenizer": "whitespace"}},
            {"id": "fuse", "op": "fuse", "inputs": ["bm25_a", "bm25_b"], "config": {"rrf_k": 60, "top_k": 25}},
        ],
    })
    pipeline = build_dag_from_config(graph.model_dump(), corpus=corpus)
    result = await pipeline.run(Query(text="alpha common", k=10, query_id="q1"))
    spans = {s.op_id: s for s in result.trace.spans}

    assert result.status == "OK"
    assert len(spans["bm25_a"].outputs) == 30
    assert len(spans["fuse"].outputs) == 25


@pytest.mark.asyncio
async def test_rerank_executor_records_its_own_truncation():
    src = _Retriever("src", [f"d{i}" for i in range(1, 21)])
    reranker = _Reranker()
    graph = PipelineGraphSpec("p", (
        SourceSpec("src", (), params={"k": 20}, adapter="src"),
        RerankSpec("rr", ("src",), adapter="rr", top_k=5),
    ), ("rr",))
    result = await DAGPipeline(graph, {"src": src, "rr": reranker}).run(Query(text="x", k=10, query_id="q"))
    span = next(s for s in result.trace.spans if s.op_id == "rr")

    assert reranker.seen_k == [5]
    assert [c.doc_id for c in span.outputs] == ["d20", "d19", "d18", "d17", "d16"]
    assert span.params["top_k"] == 5
    dropped = [c for c in span.input_groups["src"] if c.output_rank is None]
    assert len(dropped) == 15
    # The reranker scored all of them; the executor cut them. Say so, with recorded evidence.
    assert {c.drop_reason for c in dropped} == {"truncated"}
    assert {c.decision_evidence for c in dropped} == {"recorded"}


@pytest.mark.asyncio
async def test_duplicate_adapter_outputs_are_deduplicated_and_recorded():
    def src(query: Query) -> RetrievalResult:
        return RetrievalResult([Document("d1", "t", 1.0, 1), Document("d1", "t", 0.9, 2)], 1.0, "src")

    graph = PipelineGraphSpec("p", (SourceSpec("src", (), adapter="src"),), ("src",))
    result = await DAGPipeline(graph, {"src": src}).run(Query(text="x", query_id="q"))
    span = result.trace.spans[0]

    assert result.status == "OK"
    assert [c.doc_id for c in span.outputs] == ["d1"]
    assert span.params["dropped_duplicates"] == ["d1"]


@pytest.mark.asyncio
async def test_span_construction_error_becomes_error_result(monkeypatch):
    """If the evidence model still rejects a span, the run reports ERROR with the traceback."""
    def boom(self, execution):
        raise ValueError("lineage rejected")

    monkeypatch.setattr(DAGPipeline, "_span", boom)
    pipeline, _, _ = _hybrid()
    result = await pipeline.run(Query(text="q", k=10, query_id="q1"))

    assert result.status == "ERROR"
    assert result.trace is not None and result.trace.status == "ERROR"
    assert "lineage rejected" in (result.error_traceback or "")


@pytest.mark.asyncio
async def test_import_node_with_inputs_builds_as_transform_by_default():
    factory = f"{__name__}:build_post_processor"
    graph = GraphPipelineConfig.model_validate({"id": "g", "nodes": [
        {"id": "bm25", "type": "adapter.bm25", "config": {"k": 5}},
        {"id": "post", "type": "adapter.import", "inputs": ["bm25"], "config": {"factory": factory, "k": 3}},
    ]})
    pipeline = build_dag_from_config(graph.model_dump(), corpus={"d1": "x y", "d2": "x", "d3": "y"})
    result = await pipeline.run(Query(text="x y", k=10, query_id="q"))
    spans = {s.op_id: s for s in result.trace.spans}

    assert result.status == "OK"
    assert spans["post"].op_type == "TRANSFORM"
    assert spans["post"].parent_ids == ("bm25",)
    assert spans["post"].replay_policy == "OBSERVED_ABLATION"
    assert len(spans["post"].outputs) == 3


@pytest.mark.asyncio
async def test_import_node_with_explicit_op_type_is_honoured():
    factory = f"{__name__}:build_post_processor"
    graph = GraphPipelineConfig.model_validate({"id": "g", "nodes": [
        {"id": "bm25", "type": "adapter.bm25"},
        {"id": "widen", "type": "adapter.import", "op_type": "EXPAND", "inputs": ["bm25"], "config": {"factory": factory}},
    ]})
    pipeline = build_dag_from_config(graph.model_dump(), corpus={"d1": "x"})
    result = await pipeline.run(Query(text="x", query_id="q"))

    assert result.status == "OK"
    assert next(s for s in result.trace.spans if s.op_id == "widen").op_type == "EXPAND"
