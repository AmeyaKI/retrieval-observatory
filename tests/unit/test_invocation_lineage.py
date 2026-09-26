"""Operator identity is stable across invocations; candidate groups bind to the invocation that
produced them; no dataflow edge is fabricated from temporal order."""
from __future__ import annotations

import asyncio

import pytest

from retrieval_observatory.config.operators import FilterSpec, GateSpec, PipelineGraphSpec, RerankSpec, SourceSpec
from retrieval_observatory.pipeline.dag import DAGNode, DAGPipeline
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace
from retrieval_observatory.tracing import BufferedTraceSink, MemoryExporter, TraceRecorder
from retrieval_observatory.tracing.capture import CaptureSpec
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace, next_node_id
from retrieval_observatory.types import Document, Query, RetrievalResult

DOCS = [{"id": "d1", "score": 3.0}, {"id": "d2", "score": 2.0}, {"id": "d3", "score": 1.0}]


def _ctx(query_id: str = "q") -> ObserveContext:
    return ObserveContext(None, query_id, "query", "pipe", "svc")


@observe("SOURCE", op_id="source")
def source(query: str) -> list[dict]:
    return [dict(doc) for doc in DOCS]


@observe("RERANK", op_id="rerank", parent_ids=("source",))
def rerank(query: str, documents: list[dict]) -> list[dict]:
    return documents[:2]


def _trace(*spans: OperatorSpan) -> RetrievalTrace:
    return RetrievalTrace("t", "svc", None, "q", "q", "pipe", spans)


def test_next_node_id_picks_smallest_unused_suffix() -> None:
    assert next_node_id([], "rerank") == "rerank"
    assert next_node_id(["rerank"], "rerank") == "rerank#2"
    assert next_node_id(["rerank", "rerank#2", "rerank#4"], "rerank") == "rerank#3"


def test_repeated_observe_invocations_get_distinct_nodes_and_shared_operator() -> None:
    start_trace(_ctx())
    docs = source("q")
    rerank("q", docs)
    rerank("q", docs)
    twice = finish_trace()
    start_trace(_ctx())
    rerank("q", source("q"))
    once = finish_trace()

    first, second = twice.invocations_of("rerank")
    assert (first.op_id, second.op_id) == ("rerank", "rerank#2")
    assert first.operator_id == second.operator_id == "rerank"
    assert first.invocation_id != second.invocation_id
    assert second.parent_ids == ("source",)
    assert second.input_groups["source"][0].doc_id == "d1"
    assert twice.topology_hash() == once.topology_hash()


def test_declared_parent_resolves_to_latest_invocation() -> None:
    start_trace(_ctx())
    source("q")
    docs = source("q")
    rerank("q", docs)
    trace = finish_trace()

    span = trace.span("rerank")
    assert span.parent_ids == ("source#2",)
    assert span.parent_invocation_ids == (trace.span("source#2").invocation_id,)
    assert span.parent_linkage == "declared"
    assert set(span.input_groups) == {"source#2"}


def test_inputs_for_unfired_parent_record_producer_not_observed() -> None:
    @observe("RERANK", op_id="rr", parent_ids=("never",), capture=CaptureSpec(inputs=lambda bound: {"never": bound.arguments["documents"]}))
    def rr(documents: list[dict]) -> list[dict]:
        return documents

    start_trace(_ctx())
    result = rr([dict(doc) for doc in DOCS])
    trace = finish_trace()

    assert result == DOCS
    assert [(f["code"], f["detail"]) for f in trace.capture_failures] == [("producer_not_observed", "never: 3 candidates")]
    span = trace.span("rr")
    assert span.parent_linkage == "unavailable"
    assert span.parent_ids == () and span.input_groups == {}
    assert len(span.outputs) == 3


class _FakeRetriever:
    def __init__(self, ranked_ids: list[str]):
        self._ids = ranked_ids

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [Document(id=i, text="", score=1.0 / (r + 1), rank=r + 1) for r, i in enumerate(self._ids)]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id="fake")


@pytest.mark.asyncio
async def test_dag_spans_carry_recorded_invocation_links() -> None:
    pipeline = DAGPipeline(
        pipeline_id="hybrid",
        nodes=[
            DAGNode("bm25", "SOURCE", adapter=_FakeRetriever(["d1", "d2"]), k=2),
            DAGNode("dense", "SOURCE", adapter=_FakeRetriever(["d2", "d3"]), k=2),
            DAGNode("fuse", "FUSE", inputs=["bm25", "dense"]),
        ],
        output_id="fuse",
    )
    trace = (await pipeline.run(Query(text="q", k=2, query_id="q1"))).trace

    fuse = trace.span("fuse")
    assert fuse.parent_ids == ("bm25", "dense")
    assert fuse.parent_invocation_ids == (trace.span("bm25").invocation_id, trace.span("dense").invocation_id)
    assert all(fuse.parent_invocation_ids)
    assert fuse.parent_linkage == "recorded"
    assert (fuse.input_capture, fuse.output_capture) == ("recorded", "recorded")
    for op_id in ("bm25", "dense"):
        assert trace.span(op_id).input_capture == "not_applicable"
        assert trace.span(op_id).operator_id == op_id


class _Source:
    def retrieve(self, query):
        return RetrievalResult([Document("old", "", 1.0, 1), Document("new", "", 0.9, 2)], 1.0, "source")


@pytest.mark.asyncio
async def test_dag_skipped_branch_is_not_a_receiving_operator() -> None:
    graph = PipelineGraphSpec(
        "gated",
        (
            SourceSpec("source", (), adapter="source"),
            GateSpec("intent_gate", ("source",), router="route",
                     branches={"temporal": ("temporal_filter",), "generic": ("generic_reranker",)}),
            FilterSpec("temporal_filter", ("intent_gate",), predicate="filter"),
            RerankSpec("generic_reranker", ("intent_gate",), adapter="rerank"),
        ),
        ("temporal_filter", "generic_reranker"),
    )
    pipeline = DAGPipeline(graph, {
        "source": _Source(),
        "route": lambda query, documents: "temporal",
        "filter": lambda query, documents: [doc for doc in documents if doc.id == "new"],
        "rerank": lambda query, documents: RetrievalResult(list(reversed(documents)), 1.0, "rerank"),
    })
    trace = (await pipeline.run("after 2025", query_id="q-temporal")).trace

    skipped = trace.span("generic_reranker")
    assert skipped.status == "SKIPPED_BY_GATE"
    assert skipped.input_groups == {} and skipped.inputs == ()
    assert (skipped.input_capture, skipped.output_capture) == ("not_applicable", "unavailable")
    fired = trace.span("temporal_filter")
    assert fired.input_capture == "recorded"
    assert fired.parent_invocation_ids == (trace.span("intent_gate").invocation_id,)


def test_auto_instrument_source_has_no_sequential_parent() -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.documents import Document as LCDocument
    from langchain_core.retrievers import BaseRetriever

    from retrieval_observatory.tracing.auto_instrument import auto_instrument, stop_auto_instrument

    class _FixedRetriever(BaseRetriever):
        def _get_relevant_documents(self, query, *, run_manager=None):
            return [LCDocument(page_content="doc", metadata={"id": "d1"})]

    auto_instrument("langchain")
    try:
        start_trace(_ctx())
        retriever = _FixedRetriever()
        retriever.invoke("hello")
        retriever.invoke("hello")
        trace = finish_trace()
    finally:
        stop_auto_instrument()

    assert [span.op_id for span in trace.spans] == ["source__FixedRetriever", "source__FixedRetriever#2"]
    assert all(span.parent_ids == () for span in trace.spans)
    assert all(span.operator_id == "source__FixedRetriever" for span in trace.spans)
    assert all(span.invocation_id and span.input_capture == "not_applicable" for span in trace.spans)


def _recorder() -> TraceRecorder:
    return TraceRecorder("svc", BufferedTraceSink(MemoryExporter(), service_id="svc"))


def test_recorder_span_repeated_op_id_and_framework_invocation_id() -> None:
    recorder = _recorder()
    context = recorder.start_trace("q", "pipe")
    context.span("SOURCE", "src", DOCS, 1.0, op_id="src", invocation_id="run-0")
    context.span("RERANK", "rr", DOCS[:2], 1.0, op_id="rr", parent_ids=("src",), invocation_id="run-1",
                 params={"framework_parent_run_ids": ["chain-1"]})
    context.span("RERANK", "rr", DOCS[:1], 1.0, op_id="rr", parent_ids=("src",), invocation_id="run-2")
    trace = context.build_trace()
    recorder.finish(context)

    first, second = trace.invocations_of("rr")
    assert (first.op_id, second.op_id) == ("rr", "rr#2")
    assert (first.invocation_id, second.invocation_id) == ("run-1", "run-2")
    assert second.parent_ids == ("src",) and second.parent_invocation_ids == ("run-0",)
    assert first.parent_linkage == second.parent_linkage == "inferred"
    assert first.params["framework_parent_run_ids"] == ["chain-1"]
    assert trace.span("src").invocation_id == "run-0"


@observe("SOURCE", op_id="lookup")
async def lookup(query: str) -> list[dict]:
    await asyncio.sleep(0)
    return [{"id": query}]


def test_interleaved_recorder_traces_do_not_share_candidates() -> None:
    recorder = _recorder()
    a = recorder.start_trace("a", "pipe", query_id="a")
    b = recorder.start_trace("b", "pipe", query_id="b")
    a.span("SOURCE", "src", [{"id": "a1"}], 1.0, op_id="src")
    b.span("SOURCE", "src", [{"id": "b1"}], 1.0, op_id="src")
    a.span("RERANK", "rr", [{"id": "a1"}], 1.0, op_id="rr", parent_ids=("src",))
    b.span("RERANK", "rr", [{"id": "b1"}], 1.0, op_id="rr", parent_ids=("src",))
    trace_a, trace_b = a.build_trace(), b.build_trace()
    recorder.finish(b)
    recorder.finish(a)
    assert {c.doc_id for span in trace_a.spans for c in (*span.inputs, *span.outputs)} == {"a1"}
    assert {c.doc_id for span in trace_b.spans for c in (*span.inputs, *span.outputs)} == {"b1"}

    async def run(query: str) -> RetrievalTrace:
        context = recorder.start_trace(query, "pipe", query_id=query)
        await asyncio.sleep(0)
        await lookup(query)
        await asyncio.sleep(0)
        trace = context.build_trace()
        recorder.finish(context)
        return trace

    async def both():
        return await asyncio.gather(run("x"), run("y"))

    trace_x, trace_y = asyncio.run(both())
    assert [c.doc_id for span in trace_x.spans for c in span.outputs] == ["x"]
    assert [c.doc_id for span in trace_y.spans for c in span.outputs] == ["y"]
    assert trace_x.spans[0].invocation_id != trace_y.spans[0].invocation_id


def test_topology_hash_ignores_invocation_count_but_not_operator_graph() -> None:
    src = OperatorSpan.source("src", "src", ())
    one = _trace(src, OperatorSpan("rr", "RERANK", "rr", ("src",), "FIRED", 1.0))
    two = _trace(
        src,
        OperatorSpan("rr", "RERANK", "rr", ("src",), "FIRED", 1.0),
        OperatorSpan("rr#2", "RERANK", "rr", ("src",), "FIRED", 1.0, operator_id="rr"),
    )
    other_parent = _trace(
        src,
        OperatorSpan("filter", "FILTER", "filter", ("src",), "FIRED", 1.0),
        OperatorSpan("rr", "RERANK", "rr", ("filter",), "FIRED", 1.0),
    )
    other_status = _trace(src, OperatorSpan("rr", "RERANK", "rr", ("src",), "ERROR", 1.0))
    assert one.topology_hash() == two.topology_hash()
    assert len({one.topology_hash(), other_parent.topology_hash(), other_status.topology_hash()}) == 3
    assert [span.op_id for span in two.invocations_of("rr")] == ["rr", "rr#2"]


def test_span_payload_roundtrip_and_legacy_defaults() -> None:
    span = OperatorSpan(
        "rr#2", "RERANK", "rr", ("src",), "FIRED", 1.0,
        invocation_id="inv-2", operator_id="rr", parent_invocation_ids=("inv-src",), parent_linkage="recorded",
    )
    restored = OperatorSpan.from_dict(span.to_dict())
    assert (restored.operator_id, restored.parent_invocation_ids, restored.parent_linkage) == ("rr", ("inv-src",), "recorded")
    assert restored == span

    legacy = {"op_id": "rr", "op_type": "RERANK", "parent_ids": ["src"], "status": "FIRED", "outputs": []}
    with_parent = OperatorSpan.from_dict(legacy)
    assert (with_parent.operator_id, with_parent.parent_invocation_ids, with_parent.parent_linkage) == ("rr", (), "declared")
    assert OperatorSpan.from_dict({**legacy, "parent_ids": []}).parent_linkage == "recorded"
    assert OperatorSpan("rr", "RERANK", "rr", (), "FIRED", 1.0).operator_id == "rr"
    with pytest.raises(ValueError):
        OperatorSpan("rr", "RERANK", "rr", (), "FIRED", 1.0, parent_linkage="guessed")
