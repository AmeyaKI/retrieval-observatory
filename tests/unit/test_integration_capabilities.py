"""Verify reports every capability of master plan section 3.5 from observed evidence, not from
the agent-authored manifest: fabricated links, reused invocations, missing actual inputs and
unobserved declared routes are named precisely, and a limitation is not a failure."""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from retrieval_observatory.integrations.model import (
    CAPABILITY_NAMES,
    CAPABILITY_STATUSES,
    IntegrationManifest,
    OperatorMapping,
    VerificationScenario,
)
from retrieval_observatory.integrations.verify import verify_observed_traces
from retrieval_observatory.sdk.observe import observe, trace_scope
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

SOURCE = OperatorMapping("source", "SOURCE", "source", "app.py")
RERANK = OperatorMapping("rerank", "RERANK", "rerank", "app.py", ("source",))
FILTER = OperatorMapping("filter", "FILTER", "filter", "app.py", ("source",))
GATE = OperatorMapping("gate", "GATE", "intent_gate", "app.py")
BM25 = OperatorMapping("bm25", "SOURCE", "bm25", "app.py")
DENSE = OperatorMapping("dense", "SOURCE", "dense", "app.py")
FUSE = OperatorMapping("fuse", "FUSE", "fuse", "app.py", ("bm25", "dense"))
HYBRID = VerificationScenario("hybrid", "hybrid question", ("gate", "bm25", "dense", "fuse"))
LEXICAL = VerificationScenario("lexical_only", "lexical question", ("gate", "bm25"), route="lexical_only")


def _docs(*ids: str, origin: str = "source") -> tuple[Candidate, ...]:
    return tuple(Candidate(doc_id, float(len(ids) - index), index + 1, origin_op_ids=(origin,)) for index, doc_id in enumerate(ids))


def _span(op_id, op_type, parents=(), *, inputs=None, outputs=(), status="FIRED", input_capture=None, **kwargs):
    parents = tuple(parents)
    if input_capture is None:
        input_capture = "recorded" if parents else "not_applicable"
    return OperatorSpan(
        op_id, op_type, op_id, parents, status, 1.0,
        input_groups=dict(inputs or {}), outputs=tuple(outputs),
        input_capture=input_capture, operator_id=op_id.split("#")[0], **kwargs,
    )


def _trace(trace_id, spans, *, query="what is retrieval", query_id=None, final=None, status="OK", **kwargs):
    spans = tuple(spans)
    parents = {parent for span in spans for parent in span.parent_ids}
    final_ids = tuple(final) if final is not None else tuple(span.op_id for span in spans if span.op_id not in parents)
    return RetrievalTrace(
        trace_id, "svc", None, query_id or query.replace(" ", "-"), query, "pipe", spans, final_ids,
        datetime.now(timezone.utc), status=status, timing=TraceTiming(2.0, 1.0, 1.0), **kwargs,
    )


def _manifest(*operators, scenarios=(), **kwargs) -> IntegrationManifest:
    return IntegrationManifest(2, "plan", "svc", "pipe", tuple(operators), {"doc_id": "id"}, tuple(scenarios), **kwargs)


def _source_rerank_trace(trace_id="t1", *, query="what is retrieval", source_ids=("d1", "d2", "d3")):
    docs = _docs(*source_ids)
    return _trace(trace_id, [
        _span("source", "SOURCE", outputs=docs),
        _span("rerank", "RERANK", ("source",), inputs={"source": docs}, outputs=_docs(*source_ids[:2])),
    ], query=query)


def _gate(route: str):
    return _span("gate", "GATE", gate_values={"selected_route": route})


def _hybrid_trace(trace_id="h1"):
    lexical, semantic = _docs("d1", "d2", origin="bm25"), _docs("d3", origin="dense")
    return _trace(trace_id, [
        _gate("hybrid"),
        _span("bm25", "SOURCE", outputs=lexical),
        _span("dense", "SOURCE", outputs=semantic),
        _span("fuse", "FUSE", ("bm25", "dense"), inputs={"bm25": lexical, "dense": semantic}, outputs=_docs("d1", "d3", "d2")),
    ], query="hybrid question")


def _lexical_trace(trace_id="l1"):
    lexical = _docs("d1", "d2", origin="bm25")
    return _trace(trace_id, [
        _gate("lexical_only"),
        _span("bm25", "SOURCE", outputs=lexical),
        _span("dense", "SOURCE", status="SKIPPED_BY_GATE", output_capture="unavailable"),
    ], query="lexical question")


def _failures(result, capability: str) -> list[dict]:
    return result.capabilities[capability]["failures"]


def _codes(result, capability: str) -> list[str]:
    return [failure["code"] for failure in _failures(result, capability)]


def test_every_capability_is_reported_with_status_evidence_scope_and_failures() -> None:
    scenario = VerificationScenario("representative", "what is retrieval", ("source", "rerank"))
    result = verify_observed_traces(_manifest(SOURCE, RERANK, scenarios=[scenario]), [_source_rerank_trace()])

    assert set(result.capabilities) == set(CAPABILITY_NAMES)
    for capability in result.capabilities.values():
        assert capability["status"] in CAPABILITY_STATUSES
        assert isinstance(capability["evidence"], dict) and capability["evidence"]
        assert isinstance(capability["scope"], str) and capability["scope"]
        assert all({"code", "detail", "fix", "op_id"} <= set(failure) for failure in capability["failures"])
        if capability["status"] != "ready":
            assert capability["failures"]
    assert {name: capability["status"] for name, capability in result.capabilities.items()} == {
        "topology_observed": "ready",
        "actual_input_output_capture": "ready",
        "candidate_identity": "ready",
        "query_identity": "ready",
        "final_output_capture": "ready",
        "judgment_mapping": "unavailable",
        "declared_route_coverage": "ready",
        "cross_run_entity_alignment": "partial",
    }
    assert result.status == "partial" and result.errors == ()
    assert [check.check_id for check in result.checks] == list(CAPABILITY_NAMES)
    assert {check.check_id: check.status for check in result.checks}["judgment_mapping"] == "error"
    assert result.observed_operator_ids == ("rerank", "source")


def test_fabricated_parent_relationship_is_detected() -> None:
    docs = _docs("d1", "d2", "d3")
    trace = _trace("t1", [
        _span("source", "SOURCE", outputs=docs),
        _span("rerank", "RERANK", ("source",), inputs={"source": _docs("x1", "x2")}, outputs=_docs("x1")),
    ])
    result = verify_observed_traces(_manifest(SOURCE, RERANK), [trace])

    failure = next(item for item in _failures(result, "topology_observed") if item["code"] == "parent_inputs_unrelated")
    assert "rerank" in failure["detail"] and "source" in failure["detail"] and "2 of 2" in failure["detail"]
    assert "not instrumented" in failure["detail"] and "fabricated" in failure["detail"]
    assert failure["op_id"] == "rerank"
    assert result.capabilities["topology_observed"]["status"] == "unavailable"
    assert result.capabilities["topology_observed"]["evidence"]["traces_valid"] == 0
    assert result.status == "failed"
    assert any("parent_inputs_unrelated" in error for error in result.errors)


def test_reused_invocation_id_is_detected() -> None:
    docs = _docs("d1", "d2")
    trace = _trace("t1", [
        _span("source", "SOURCE", outputs=docs, invocation_id="inv-1"),
        _span("rerank", "RERANK", ("source",), inputs={"source": docs}, outputs=docs, invocation_id="inv-1", parent_invocation_ids=("inv-1",)),
    ])
    result = verify_observed_traces(_manifest(SOURCE, RERANK), [trace])

    failure = next(item for item in _failures(result, "topology_observed") if item["code"] == "invocation_id_reused")
    assert "inv-1" in failure["detail"] and failure["op_id"] == "rerank"
    assert result.status == "failed"


def test_parent_invocation_reference_must_exist() -> None:
    docs = _docs("d1", "d2")
    trace = _trace("t1", [
        _span("source", "SOURCE", outputs=docs, invocation_id="inv-1"),
        _span("rerank", "RERANK", ("source",), inputs={"source": docs}, outputs=docs, invocation_id="inv-2", parent_invocation_ids=("inv-9",)),
    ])
    result = verify_observed_traces(_manifest(SOURCE, RERANK), [trace])

    failure = next(item for item in _failures(result, "topology_observed") if item["code"] == "parent_invocation_unknown")
    assert "inv-9" in failure["detail"] and failure["op_id"] == "rerank"
    assert result.status == "failed"


def test_matching_operator_count_is_insufficient() -> None:
    docs = _docs("d1", "d2")
    trace = _trace("t1", [
        _span("source", "SOURCE", outputs=docs),
        _span("rerank", "RERANK", ("source",), input_capture="unavailable", outputs=(), output_capture="unavailable"),
    ])
    result = verify_observed_traces(_manifest(SOURCE, RERANK), [trace])

    assert result.status != "ready"
    assert set(result.observed_operator_ids) == {"source", "rerank"}
    assert result.capabilities["actual_input_output_capture"]["status"] != "ready"
    failure = next(item for item in _failures(result, "actual_input_output_capture") if item["code"] == "missing_actual_inputs")
    assert failure["op_id"] == "rerank" and "1 of 1 invocations of rerank" in failure["detail"]
    assert "retobs_adapter" in failure["fix"] and "rerank_capture" in failure["fix"]
    assert result.capabilities["actual_input_output_capture"]["evidence"]["by_operator"]["rerank"]["unavailable"] == 1


def test_conditional_route_skipped_in_one_query_does_not_fail_declared_scope() -> None:
    manifest = _manifest(GATE, BM25, DENSE, FUSE, scenarios=[HYBRID, LEXICAL])
    result = verify_observed_traces(manifest, [_hybrid_trace(), _lexical_trace()])

    coverage = result.capabilities["declared_route_coverage"]
    assert coverage["status"] == "ready", coverage["failures"]
    assert coverage["evidence"]["observed_scenarios"] == 2 and coverage["evidence"]["unobserved"] == []
    assert coverage["evidence"]["satisfied_by"] == {"hybrid": "h1", "lexical_only": "l1"}
    assert coverage["evidence"]["observed_routes"] == ["hybrid", "lexical_only"]
    assert result.capabilities["topology_observed"]["status"] == "ready"
    assert result.capabilities["final_output_capture"]["status"] == "ready"
    assert not any("dense" in failure["detail"] for capability in result.capabilities.values() for failure in capability["failures"])


def test_unobserved_scenario_is_reported_precisely() -> None:
    manifest = _manifest(GATE, BM25, DENSE, FUSE, scenarios=[HYBRID, LEXICAL])
    result = verify_observed_traces(manifest, [_hybrid_trace()])

    coverage = result.capabilities["declared_route_coverage"]
    assert coverage["status"] == "partial"
    assert coverage["evidence"]["unobserved"] == ["lexical_only"]
    assert coverage["evidence"]["satisfied_by"] == {"hybrid": "h1"}
    assert "1 of 2 declared scenarios" in coverage["scope"] and "declared scenarios only" in coverage["scope"]
    [failure] = coverage["failures"]
    assert failure["code"] == "scenario_unobserved"
    assert "lexical_only" in failure["detail"] and "lexical question" in failure["detail"]
    assert "run the scenario's command" in failure["fix"]
    assert result.status == "partial"


def test_undeclared_operator_observed_marks_topology_partial() -> None:
    result = verify_observed_traces(_manifest(SOURCE), [_source_rerank_trace()])

    topology = result.capabilities["topology_observed"]
    assert topology["status"] == "partial"
    assert topology["evidence"]["undeclared_operators"] == ["rerank"]
    failure = next(item for item in topology["failures"] if item["code"] == "undeclared_operator_observed")
    assert "rerank" in failure["detail"] and failure["op_id"] == "rerank"
    assert result.status == "partial"


def test_unobserved_transition_before_return_is_flagged() -> None:
    docs = _docs("d1", "d2", "d3")
    returned = OperatorSpan(
        "return", "TRANSFORM", "returned result", ("source",), "FIRED", 0.0,
        input_groups={"source": docs}, outputs=_docs("d1", "d2"),
        params={"boundary": "callable_return"}, input_capture="inferred", parent_linkage="declared",
    )
    trace = _trace("t1", [_span("source", "SOURCE", outputs=docs), returned])
    result = verify_observed_traces(_manifest(SOURCE), [trace])

    topology = result.capabilities["topology_observed"]
    assert topology["status"] == "partial"
    failure = next(item for item in topology["failures"] if item["code"] == "unobserved_transition_before_return")
    assert "source" in failure["detail"] and "1 ids" in failure["detail"] and "not instrumented" in failure["detail"]
    assert topology["evidence"]["undeclared_operators"] == []
    assert result.capabilities["final_output_capture"]["status"] == "ready"
    assert result.capabilities["final_output_capture"]["evidence"]["with_return_boundary"] == 1
    assert result.capabilities["actual_input_output_capture"]["status"] == "ready"


def _write_qrels(root: Path, doc_ids: list[str]) -> str:
    path = root / "data" / "qrels.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"query_id": "what-is-retrieval", "relevant_doc_ids": doc_ids}) + "\n", encoding="utf-8")
    return "data/qrels.jsonl"


def test_judgment_mapping_uses_declared_qrels(tmp_path: Path) -> None:
    qrels = _write_qrels(tmp_path, ["d1", "d2"])
    matched = verify_observed_traces(_manifest(SOURCE, RERANK, judgments={"qrels": qrels}), [_source_rerank_trace()], project_root=tmp_path)
    judgments = matched.capabilities["judgment_mapping"]
    assert judgments["status"] == "ready", judgments["failures"]
    assert judgments["evidence"] == {
        "judged_queries": 1, "judged_entities": 2, "observed_entities": 3, "matched_entities": 2, "matched_queries": 1,
    }

    _write_qrels(tmp_path, ["x1", "x2"])
    mismatched = verify_observed_traces(_manifest(SOURCE, RERANK, judgments={"qrels": qrels}), [_source_rerank_trace()], project_root=tmp_path)
    judgments = mismatched.capabilities["judgment_mapping"]
    assert judgments["status"] == "partial"
    [failure] = judgments["failures"]
    assert failure["code"] == "judgment_ids_unmatched" and "0 of 2 judged" in failure["detail"]

    missing = verify_observed_traces(_manifest(SOURCE, RERANK, judgments={"qrels": "data/absent.jsonl"}), [_source_rerank_trace()], project_root=tmp_path)
    assert missing.capabilities["judgment_mapping"]["status"] == "unavailable"
    assert _codes(missing, "judgment_mapping") == ["judgments_unavailable"]

    undeclared = verify_observed_traces(_manifest(SOURCE, RERANK), [_source_rerank_trace()], project_root=tmp_path)
    assert undeclared.capabilities["judgment_mapping"]["status"] == "unavailable"
    [failure] = _failures(undeclared, "judgment_mapping")
    assert failure["code"] == "judgments_unavailable" and "candidate movement inspection works without labels" in failure["fix"]
    assert undeclared.capabilities["actual_input_output_capture"]["status"] == "ready"
    assert undeclared.status == "partial"


def test_cross_run_alignment_needs_a_repeated_query() -> None:
    manifest = _manifest(SOURCE, RERANK)

    single = verify_observed_traces(manifest, [_source_rerank_trace("t1")])
    assert single.capabilities["cross_run_entity_alignment"]["status"] == "partial"
    assert _codes(single, "cross_run_entity_alignment") == ["alignment_unverified"]
    assert "twice" in _failures(single, "cross_run_entity_alignment")[0]["fix"]

    repeated = verify_observed_traces(manifest, [_source_rerank_trace("t1"), _source_rerank_trace("t2")])
    alignment = repeated.capabilities["cross_run_entity_alignment"]
    assert alignment["status"] == "ready", alignment["failures"]
    assert alignment["evidence"]["repeated_queries"] == 1 and alignment["evidence"]["inconsistent"] == 0

    unstable = verify_observed_traces(manifest, [_source_rerank_trace("t1"), _source_rerank_trace("t2", source_ids=("e1", "e2", "e3"))])
    alignment = unstable.capabilities["cross_run_entity_alignment"]
    assert alignment["status"] == "partial"
    unstable_ops = [item["op_id"] for item in alignment["failures"] if item["code"] == "unstable_candidate_ids"]
    assert unstable_ops == ["rerank", "source"]
    failure = next(item for item in alignment["failures"] if item["op_id"] == "source")
    assert "what is retrieval" in failure["detail"] and "stable document ids" in failure["fix"]


def test_query_identity_collision_detected() -> None:
    traces = [
        _source_rerank_trace("t1", query="first text"),
        _trace("t2", _source_rerank_trace().spans, query="second text", query_id="first-text"),
        _source_rerank_trace("t3", query="third text"),
    ]
    result = verify_observed_traces(_manifest(SOURCE, RERANK), traces)

    identity = result.capabilities["query_identity"]
    assert identity["status"] == "partial"
    failure = next(item for item in identity["failures"] if item["code"] == "query_id_collision")
    assert "first-text" in failure["detail"]
    assert identity["evidence"]["query_id_collisions"] == 1


def test_final_output_shape_unsupported_is_reported_not_invented() -> None:
    unsupported = {
        "op_id": "return", "invocation_id": None, "phase": "outputs",
        "code": "final_output_shape_unsupported", "detail": "generator: iterator_output_not_captured",
    }
    traces = [_source_rerank_trace("t1"), _source_rerank_trace("t2", query="other question")]
    traces[1].capture_failures = (unsupported,)
    result = verify_observed_traces(_manifest(SOURCE, RERANK), traces)

    final = result.capabilities["final_output_capture"]
    assert final["status"] == "partial"
    assert final["evidence"] == {"ok_traces": 2, "captured": 1, "with_return_boundary": 0}
    failure = next(item for item in final["failures"] if item["code"] == "final_output_shape_unsupported")
    assert "t2" in failure["detail"] and "mapping with a `documents` key" in failure["fix"]
    assert [span.op_id for span in traces[1].spans] == ["source", "rerank"]


async def _stored(db: str):
    store = SQLiteStore(db_path=db)
    await store.init_db()
    return await store.list_traces(TraceQuery(service_id="svc", pipeline_id="pipe"))


def test_trace_scope_records_return_boundary_and_mapping_outputs(tmp_path: Path) -> None:
    db = str(tmp_path / "scope.db")

    @observe("SOURCE", op_id="source")
    def source(query: str) -> list[dict]:
        return [{"id": "d1", "score": 3.0}, {"id": "d2", "score": 2.0}, {"id": "d3", "score": 1.0}]

    @trace_scope("svc", "pipe", db_path=db)
    def retrieve(query: str) -> dict:
        return {"documents": source(query)[:2]}

    @trace_scope("svc", "pipe", db_path=db)
    def stream(query: str):
        return (hit for hit in source(query))

    assert retrieve("mapped") == {"documents": [{"id": "d1", "score": 3.0}, {"id": "d2", "score": 2.0}]}
    streamed = stream("streamed")
    assert inspect.isgenerator(streamed)
    assert [hit["id"] for hit in streamed] == ["d1", "d2", "d3"]

    traces = {trace.query_text: trace for trace in asyncio.run(_stored(db))}
    mapped = traces["mapped"]
    assert [span.op_id for span in mapped.spans] == ["source", "return"]
    returned = mapped.span("return")
    assert [candidate.doc_id for candidate in returned.outputs] == ["d1", "d2"]
    assert returned.input_capture == "inferred" and returned.output_capture == "recorded"
    assert returned.params["boundary"] == "callable_return" and returned.parent_ids == ("source",)
    assert mapped.final_op_ids == ("return",) and mapped.capture_failures == ()

    generator_trace = traces["streamed"]
    assert [span.op_id for span in generator_trace.spans] == ["source"]
    [failure] = generator_trace.capture_failures
    assert failure["op_id"] == "return" and failure["code"] == "final_output_shape_unsupported"
    assert "iterator_output_not_captured" in failure["detail"]


def test_final_output_only_integration_is_partial_not_failed() -> None:
    docs = _docs("d1", "d2", "d3")
    trace = _trace("t1", [
        _span("source", "SOURCE", outputs=docs),
        _span("filter", "FILTER", ("source",), input_capture="unavailable", outputs=_docs("d1", "d2")),
    ])
    result = verify_observed_traces(_manifest(SOURCE, FILTER), [trace])

    assert result.status == "partial" and result.errors == ()
    capture = result.capabilities["actual_input_output_capture"]
    assert capture["status"] == "unavailable"
    failure = next(item for item in capture["failures"] if item["code"] == "missing_actual_inputs")
    assert failure["op_id"] == "filter"
    assert result.capabilities["final_output_capture"]["status"] == "ready"
    assert result.capabilities["candidate_identity"]["status"] == "ready"
