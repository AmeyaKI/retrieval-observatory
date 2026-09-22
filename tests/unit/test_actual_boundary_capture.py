"""``@observe`` records each operator's actual call boundary and never changes the call itself."""
from __future__ import annotations

import asyncio
import inspect
import traceback

import pytest

from retrieval_observatory.sdk.observe import ObserveContext, current_trace, finish_trace, observe, start_trace
from retrieval_observatory.tracing import BufferedTraceSink, MemoryExporter, TraceRecorder
from retrieval_observatory.tracing.capture import CaptureError, CaptureSpec, strict_capture
from retrieval_observatory.tracing.config import PayloadLimits
from retrieval_observatory.tracing.model import OperatorSpan
from retrieval_observatory.tracing.serialization import normalize_trace

DOCS = [{"id": "d1", "score": 3.0}, {"id": "d2", "score": 2.0}, {"id": "d3", "score": 1.0}]


def _ctx() -> ObserveContext:
    return ObserveContext(None, "q", "query", "pipe", "svc")


@observe("SOURCE", op_id="src")
def source(query: str) -> list[dict]:
    return [dict(doc) for doc in DOCS]


def test_instrumented_result_is_the_original_object() -> None:
    calls = {"sync": 0, "async": 0}
    payload = [{"id": "d1"}]

    @observe("SOURCE", op_id="sync_source")
    def sync_source():
        calls["sync"] += 1
        return payload

    @observe("SOURCE", op_id="async_source")
    async def async_source():
        calls["async"] += 1
        return payload

    start_trace(_ctx())
    assert sync_source() is payload
    assert asyncio.run(async_source()) is payload
    trace = finish_trace()
    assert calls == {"sync": 1, "async": 1}
    assert [span.op_id for span in trace.spans] == ["sync_source", "async_source"]


def test_instrumented_and_uninstrumented_ordered_ids_match() -> None:
    def rerank(query: str, documents: list[dict]) -> list[dict]:
        return sorted(documents, key=lambda doc: len(doc["id"] + query))[:2]

    plain = rerank("q", [dict(doc) for doc in DOCS])
    start_trace(_ctx())
    source("q")
    instrumented = observe("RERANK", op_id="rr", parent_ids=("src",))(rerank)("q", [dict(doc) for doc in DOCS])
    trace = finish_trace()
    assert [doc["id"] for doc in instrumented] == [doc["id"] for doc in plain]
    assert [candidate.doc_id for candidate in trace.span("rr").outputs] == [doc["id"] for doc in plain]


class MyError(Exception):
    pass


def test_application_exception_type_and_traceback_are_preserved() -> None:
    calls = 0

    @observe("SOURCE", op_id="boom")
    def boom():
        nonlocal calls
        calls += 1
        try:
            raise ValueError("inner")
        except ValueError as inner:
            raise MyError("outer") from inner

    start_trace(_ctx())
    with pytest.raises(MyError) as info:
        boom()
    trace = finish_trace("ERROR")
    assert type(info.value) is MyError
    assert isinstance(info.value.__cause__, ValueError)
    assert any(frame.name == "boom" for frame in traceback.extract_tb(info.tb))
    assert trace.span("boom").status == "ERROR"
    assert trace.span("boom").error == "MyError: outer"
    assert calls == 1


async def test_async_cancellation_propagates_and_is_recorded() -> None:
    entered = asyncio.Event()

    @observe("SOURCE", op_id="slow")
    async def slow():
        entered.set()
        await asyncio.sleep(30)
        return []

    trace = start_trace(_ctx())
    task = asyncio.create_task(slow())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert trace.span("slow").status == "ERROR"
    assert trace.span("slow").error == "cancelled"
    finish_trace("ERROR")


def test_pre_call_input_order_survives_in_place_reranker() -> None:
    @observe("RERANK", op_id="rr", parent_ids=("src",))
    def reverse_in_place(query: str, documents: list[dict]) -> list[dict]:
        documents.reverse()
        return documents

    start_trace(_ctx())
    source("q")
    documents = [dict(doc) for doc in DOCS]
    result = reverse_in_place("q", documents)
    trace = finish_trace()
    span = trace.span("rr")
    assert result is documents
    assert span.input_capture == "recorded"
    assert [(c.doc_id, c.input_rank) for c in span.input_groups["src"]] == [("d1", 1), ("d2", 2), ("d3", 3)]
    assert [(c.doc_id, c.rank) for c in span.outputs] == [("d3", 1), ("d2", 2), ("d1", 3)]


def test_broken_input_mapping_yields_capture_failure_not_fabricated_inputs() -> None:
    def broken(bound):
        raise KeyError("no such argument")

    @observe("RERANK", op_id="rr", parent_ids=("src",), capture=CaptureSpec(inputs=broken))
    def rerank(query: str, documents: list[dict]) -> list[dict]:
        return documents

    start_trace(_ctx())
    source("q")
    documents = [dict(doc) for doc in DOCS]
    assert rerank("q", documents) is documents
    trace = finish_trace()
    span = trace.span("rr")
    assert span.input_capture == "unavailable"
    assert span.input_groups == {}
    assert span.output_capture == "recorded"
    assert [failure["code"] for failure in trace.capture_failures] == ["input_mapping_failed"]
    assert trace.capture_failures[0]["op_id"] == "rr"
    assert trace.capture_failures[0]["invocation_id"] == span.invocation_id
    assert trace.capture.incomplete_boundary_count == 1


def test_broken_output_mapping_yields_capture_failure_not_empty_output() -> None:
    def broken(result):
        raise TypeError("cannot read result")

    @observe("RERANK", op_id="rr", parent_ids=("src",), capture=CaptureSpec(outputs=broken))
    def rerank(query: str, documents: list[dict]) -> list[dict]:
        return documents[:1]

    start_trace(_ctx())
    source("q")
    rerank("q", [dict(doc) for doc in DOCS])
    trace = finish_trace()
    span = trace.span("rr")
    assert span.output_capture == "unavailable"
    assert span.outputs == ()
    assert span.input_capture == "recorded"
    assert [c.doc_id for c in span.input_groups["src"]] == ["d1", "d2", "d3"]
    assert all(c.decision_evidence == "unavailable" and c.drop_reason is None for c in span.input_groups["src"])
    assert [failure["code"] for failure in trace.capture_failures] == ["output_mapping_failed"]


def test_generator_result_is_not_consumed() -> None:
    @observe("SOURCE", op_id="gen")
    def generate():
        yield from DOCS

    start_trace(_ctx())
    result = generate()
    assert inspect.isgenerator(result)
    assert list(result) == DOCS
    trace = finish_trace()
    assert trace.span("gen").output_capture == "unavailable"
    assert trace.span("gen").outputs == ()
    assert [failure["code"] for failure in trace.capture_failures] == ["iterator_output_not_captured"]


def test_unsupported_output_shape_is_unavailable_not_empty() -> None:
    @observe("SOURCE", op_id="mapping")
    def as_mapping():
        return {"payload": DOCS}

    start_trace(_ctx())
    assert as_mapping() == {"payload": DOCS}
    trace = finish_trace()
    assert trace.span("mapping").output_capture == "unavailable"
    assert [failure["code"] for failure in trace.capture_failures] == ["unsupported_output_shape"]


def test_mapping_with_a_candidate_key_is_recorded() -> None:
    @observe("SOURCE", op_id="mapping")
    def as_mapping():
        return {"total": 3, "hits": DOCS}

    start_trace(_ctx())
    assert as_mapping() == {"total": 3, "hits": DOCS}
    trace = finish_trace()
    assert trace.span("mapping").output_capture == "recorded"
    assert [candidate.doc_id for candidate in trace.span("mapping").outputs] == ["d1", "d2", "d3"]
    assert trace.capture_failures == ()


def test_none_empty_mapping_and_empty_group_are_distinct() -> None:
    def make(op_id: str, mapped):
        @observe("FILTER", op_id=op_id, parent_ids=("src",), capture=CaptureSpec(inputs=lambda bound: mapped))
        def op(query: str, documents: list[dict]) -> list[dict]:
            return documents

        return op

    start_trace(_ctx())
    source("q")
    for op_id, mapped in (("none", None), ("empty_mapping", {}), ("empty_group", {"src": []})):
        make(op_id, mapped)("q", [dict(doc) for doc in DOCS])
    trace = finish_trace()
    assert trace.span("none").input_capture == "inferred"
    assert [c.doc_id for c in trace.span("none").input_groups["src"]] == ["d1", "d2", "d3"]
    assert trace.span("empty_mapping").input_capture == "recorded"
    assert trace.span("empty_mapping").input_groups == {}
    assert trace.span("empty_group").input_capture == "recorded"
    assert trace.span("empty_group").input_groups == {"src": ()}
    assert trace.capture_failures == ()


def test_default_input_capture_rules() -> None:
    @observe("SOURCE", op_id="dense")
    def dense(query: str) -> list[dict]:
        return [{"id": "d9", "score": 9.0}]

    @observe("RERANK", op_id="by_name", parent_ids=("src",))
    def by_name(query: str, documents: list[dict]) -> list[dict]:
        return documents

    @observe("FUSE", op_id="by_parent", parent_ids=("src", "dense"))
    def by_parent(src: list[dict], dense: list[dict]) -> list[dict]:
        return src + dense

    @observe("FUSE", op_id="by_lane", parent_ids=("src", "dense"))
    def by_lane(lanes: list[list[dict]]) -> list[dict]:
        return [hit for lane in lanes for hit in lane]

    @observe("FILTER", op_id="opaque", parent_ids=("src",))
    def opaque(query: str, settings: dict) -> list[dict]:
        return [dict(doc) for doc in DOCS[:1]]

    start_trace(_ctx())
    lexical, semantic = source("q"), dense("q")
    by_name("q", lexical)
    by_parent(lexical, semantic)
    by_lane([lexical, semantic])
    opaque("q", {"k": 1})
    trace = finish_trace()
    assert trace.span("by_name").input_capture == "recorded"
    assert [c.doc_id for c in trace.span("by_name").input_groups["src"]] == ["d1", "d2", "d3"]
    assert trace.span("by_parent").input_capture == "recorded"
    assert {parent: [c.doc_id for c in group] for parent, group in trace.span("by_parent").input_groups.items()} == {
        "src": ["d1", "d2", "d3"],
        "dense": ["d9"],
    }
    assert trace.span("by_lane").input_capture == "positional"
    assert {parent: [c.doc_id for c in group] for parent, group in trace.span("by_lane").input_groups.items()} == {
        "src": ["d1", "d2", "d3"],
        "dense": ["d9"],
    }
    assert trace.span("opaque").input_capture == "inferred"
    assert [c.doc_id for c in trace.span("opaque").input_groups["src"]] == ["d1", "d2", "d3"]
    assert trace.capture_failures == ()
    assert trace.capture.incomplete_boundary_count == 2  # the positional and the inferred span


def test_undeclared_input_group_is_a_capture_failure() -> None:
    @observe("RERANK", op_id="rr", parent_ids=("src",), capture=CaptureSpec(inputs=lambda bound: {"other": DOCS}))
    def rerank(query: str, documents: list[dict]) -> list[dict]:
        return documents

    start_trace(_ctx())
    source("q")
    rerank("q", [dict(doc) for doc in DOCS])
    trace = finish_trace()
    assert trace.span("rr").input_capture == "unavailable"
    assert trace.span("rr").input_groups == {}
    assert [failure["code"] for failure in trace.capture_failures] == ["undeclared_input_group"]


def test_strict_mode_raises_after_the_application_call() -> None:
    calls = 0

    @observe("SOURCE", op_id="mapping")
    def as_mapping():
        nonlocal calls
        calls += 1
        return {"payload": DOCS}

    start_trace(_ctx())
    with strict_capture():
        with pytest.raises(CaptureError, match="unsupported_output_shape"):
            as_mapping()
    strict = finish_trace()
    assert calls == 1
    assert strict.span("mapping").output_capture == "unavailable"
    assert [failure["code"] for failure in strict.capture_failures] == ["unsupported_output_shape"]

    start_trace(_ctx())
    assert as_mapping() == {"payload": DOCS}
    lenient = finish_trace()
    assert calls == 2
    assert [failure["code"] for failure in lenient.capture_failures] == ["unsupported_output_shape"]


class Ranker:
    def rank(self, query: str, documents: list[dict], *, k: int = 5) -> list[dict]:
        return documents[:k]

    decorated = observe("RERANK", op_id="rr", parent_ids=("src",))(rank)


def test_method_binding_and_signature_preserved() -> None:
    assert inspect.signature(Ranker.decorated) == inspect.signature(Ranker.rank)
    assert Ranker.decorated.__wrapped__ is Ranker.rank
    start_trace(_ctx())
    source("q")
    result = Ranker().decorated("q", [dict(doc) for doc in DOCS], k=2)
    trace = finish_trace()
    span = trace.span("rr")
    assert [doc["id"] for doc in result] == ["d1", "d2"]
    assert span.source_ref is not None and span.source_ref.endswith(":Ranker.rank")
    assert span.input_capture == "recorded"
    assert [c.doc_id for c in span.input_groups["src"]] == ["d1", "d2", "d3"]
    assert span.params == {"k": 2}


def test_recorder_span_inputs_are_labelled_inferred_unless_supplied() -> None:
    recorder = TraceRecorder("svc", BufferedTraceSink(MemoryExporter(), service_id="svc"))
    context = recorder.start_trace("q", "pipe")
    context.span("SOURCE", "src", DOCS, 1.0, op_id="src")
    context.span("RERANK", "inferred", DOCS[:2], 1.0, op_id="inferred", parent_ids=("src",))
    context.span("RERANK", "actual", DOCS[:1], 1.0, op_id="actual", parent_ids=("src",), input_groups={"src": DOCS[::-1]})
    trace = context.build_trace()
    recorder.finish(context)
    assert trace.span("src").input_capture == "not_applicable"
    assert trace.span("inferred").input_capture == "inferred"
    assert trace.span("actual").input_capture == "recorded"
    assert [c.doc_id for c in trace.span("actual").input_groups["src"]] == ["d3", "d2", "d1"]
    assert trace.capture.incomplete_boundary_count == 1
    assert trace.capture_failures == ()


def test_legacy_span_payload_parses_with_inferred_labels() -> None:
    fired = {"op_id": "rr", "op_type": "RERANK", "parent_ids": ["src"], "status": "FIRED", "outputs": []}
    assert OperatorSpan.from_dict({**fired, "input_groups": {"src": [{"doc_id": "d1", "score": 1.0, "rank": 1}]}}).input_capture == "inferred"
    assert OperatorSpan.from_dict(fired).input_capture == "unavailable"
    assert OperatorSpan.from_dict({**fired, "parent_ids": []}).input_capture == "not_applicable"
    assert OperatorSpan.from_dict(fired).output_capture == "recorded"
    assert OperatorSpan.from_dict({**fired, "status": "ERROR"}).output_capture == "unavailable"
    span = OperatorSpan.from_dict(fired)
    assert span.invocation_id is None and span.source_ref is None
    with pytest.raises(ValueError):
        OperatorSpan.from_dict({**fired, "input_capture": "guessed"})


def test_redaction_does_not_touch_identity() -> None:
    @observe("SOURCE", op_id="secret_source")
    def secret_source() -> list[dict]:
        return [{"id": "d1", "score": 1.0, "metadata": {"api_key": "hunter2", "text": "hello"}}]

    start_trace(_ctx())
    secret_source()
    trace = finish_trace()
    normalized = normalize_trace(trace, limits=PayloadLimits(), redacted_keys=frozenset({"api_key"}))
    candidate = normalized.payload["spans"][0]["outputs"][0]
    assert candidate["metadata"]["api_key"] == "[REDACTED]"
    assert candidate["metadata"]["text"] == "hello"
    assert (candidate["candidate_id"], candidate["doc_id"], candidate["rank"]) == ("d1", "d1", 1)
    assert normalized.payload["spans"][0]["invocation_id"] == trace.spans[0].invocation_id


async def test_interleaved_async_traces_do_not_share_spans() -> None:
    @observe("SOURCE", op_id="lookup")
    async def lookup(query: str) -> list[dict]:
        await asyncio.sleep(0)
        return [{"id": query}]

    async def run(query: str):
        start_trace(ObserveContext(None, query, query, "pipe", "svc"))
        await asyncio.sleep(0)
        await lookup(query)
        await asyncio.sleep(0)
        return finish_trace()

    first, second = await asyncio.gather(run("a"), run("b"))
    assert [c.doc_id for span in first.spans for c in span.outputs] == ["a"]
    assert [c.doc_id for span in second.spans for c in span.outputs] == ["b"]
    assert first.spans[0].invocation_id != second.spans[0].invocation_id
    assert current_trace() is None


def test_gate_decision_is_recorded_as_selected_route_not_an_unsupported_output() -> None:
    """A gate returns a route, not candidates: the route is its recorded output."""
    from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace

    @observe("GATE", op_id="intent_gate")
    def intent_gate(query: str) -> str:
        return "lexical_only"

    @observe("SOURCE", op_id="bm25", parent_ids=("intent_gate",))
    def bm25(query: str, route: str) -> list[dict]:
        return [{"id": "a", "score": 1.0}]

    start_trace(ObserveContext(None, "q1", "query", "pipe", "svc"))
    bm25("query", intent_gate("query"))
    trace = finish_trace()

    gate, source = trace.spans
    assert gate.gate_values == {"selected_route": "lexical_only"}
    assert gate.output_capture == "recorded" and gate.outputs == ()
    assert trace.capture_failures == ()
    # The gate is a topology parent of the source, but it hands down a decision, not candidates.
    assert source.parent_ids == ("intent_gate",)
    assert source.input_capture == "not_applicable" and source.parent_linkage == "recorded"
    assert [c.doc_id for c in source.outputs] == ["a"]


def test_gate_passing_candidates_through_is_captured_as_candidates() -> None:
    from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace

    @observe("SOURCE", op_id="source")
    def source(query: str) -> list[dict]:
        return [{"id": "a", "score": 1.0}, {"id": "b", "score": 0.5}]

    @observe("GATE", op_id="threshold_gate", parent_ids=("source",))
    def threshold_gate(candidates: list[dict]) -> list[dict]:
        return [c for c in candidates if c["score"] >= 1.0]

    start_trace(ObserveContext(None, "q1", "query", "pipe", "svc"))
    threshold_gate(source("query"))
    trace = finish_trace()

    gate = trace.spans[1]
    assert gate.gate_values == {}
    assert [c.doc_id for c in gate.outputs] == ["a"] and gate.input_capture == "recorded"


def test_candidate_ids_are_read_from_llamaindex_style_nodes() -> None:
    """A NodeWithScore exposes ``node_id`` (and ``node.id_``), not ``id``; positional ids must not be invented."""
    from types import SimpleNamespace

    from retrieval_observatory.tracing.candidates import to_candidates

    node = SimpleNamespace(node_id="d-llama-current", id_="d-llama-current", metadata={"rank": 1})
    items = [SimpleNamespace(node=node, node_id="d-llama-current", score=0.94, metadata={"rank": 1}), {"id_": "d-plain"}]

    candidates = to_candidates(items, "llamaindex_retriever")

    assert [c.doc_id for c in candidates] == ["d-llama-current", "d-plain"]
    assert all(c.identity_evidence == "recorded" for c in candidates)
