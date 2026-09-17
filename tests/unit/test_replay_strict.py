"""Strict counterfactual replay: child projection, producer removal, lineage bookkeeping.

Each test mirrors a scenario from the tracing review. Replay never fabricates a
downstream decision: when a child would have to judge documents it never observed
the result is ``indeterminate``.
"""
from __future__ import annotations

import pytest

from retrieval_observatory.tracing import attribution
from retrieval_observatory.tracing.attribution import (
    _find_final_span,
    _metric_at_k,
    operator_marginal_contribution,
    operator_marginal_contributions,
)
from retrieval_observatory.tracing.candidate_history import candidate_history
from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.config import PayloadLimits
from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.model import Candidate, CaptureMetadata, OperatorSpan, RetrievalTrace
from retrieval_observatory.tracing.replay import (
    attribute_miss,
    replay_assumptions,
    simulate_without_operator,
    without_operator,
)
from retrieval_observatory.tracing.serialization import normalize_trace
from retrieval_observatory.types import Document


def C(doc: str, rank: int, score: float | None = None, origin=(), **kw) -> Candidate:
    return Candidate(doc_id=doc, score=score if score is not None else 1.0 / rank, rank=rank, origin_op_ids=tuple(origin), **kw)


def span(op_id, op_type, parents, outputs, policy="EXACT", inputs=None, input_groups=None, status="FIRED", **kw):
    return OperatorSpan(
        op_id=op_id, op_type=op_type, op_name=op_id, parent_ids=tuple(parents), status=status,
        deterministic=policy == "EXACT", replay_policy=policy, latency_ms=1.0,
        outputs=tuple(outputs), inputs=tuple(inputs or ()), input_groups=input_groups or {}, **kw,
    )


def trace(spans, finals, tid="t", qid="q1") -> RetrievalTrace:
    return RetrievalTrace(
        trace_id=tid, service_id="svc", run_id="r", query_id=qid, query_text="q", pipeline_id="p",
        spans=list(spans), final_op_ids=tuple(finals),
    )


def docs(candidates) -> list:
    return [(c.doc_id, c.rank) for c in candidates]


# --- bug 1: passthrough removal must not overwrite the child's recorded outputs ---


def test_filter_removal_is_indeterminate_when_child_never_saw_the_docs() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"]), C("d3", 3, 0.8, ["src"])])
    flt = span("filter", "FILTER", ["src"], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"])], inputs=src.outputs)
    rr = span("rerank", "RERANK", ["filter"], [C("d2", 1, 5.0, ["src"]), C("d1", 2, 4.0, ["src"])],
              policy="OBSERVED_ABLATION", inputs=flt.outputs)
    t = trace([src, flt, rr], ["rerank"])

    result = simulate_without_operator(t, "filter")
    assert result.status == "indeterminate"
    assert result.evidence_class == "unavailable"
    assert result.trace is None
    assert "rerank" in result.reason and "never observed 1" in result.reason
    with pytest.raises(ValueError):
        without_operator(t, "filter")

    rows = operator_marginal_contribution([t], "filter", {"q1": {"d2": 1}}, metric="mrr", k=10)
    assert rows[0].result_status == "indeterminate"
    assert rows[0].delta is None


def test_root_gate_removal_leaves_source_untouched() -> None:
    gate = span("gate", "GATE", [], [], gate_values={"intent": "x"})
    src = span("src", "SOURCE", ["gate"], [C("d1", 1, 1.0, ["src"])])
    cf = without_operator(trace([gate, src], ["src"]), "gate")
    assert docs(cf.span("src").outputs) == [("d1", 1)]


def test_rerank_removal_keeps_child_filter_decision() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"]), C("bad", 3, 0.8, ["src"])])
    rr = span("rerank", "RERANK", ["src"], [C("bad", 1, 5.0, ["src"]), C("d1", 2, 4.0, ["src"]), C("d2", 3, 3.0, ["src"])],
              policy="OBSERVED_ABLATION", inputs=src.outputs)
    flt = span("pii_filter", "FILTER", ["rerank"], [C("d1", 1, 4.0, ["src"]), C("d2", 2, 3.0, ["src"])], inputs=rr.outputs)
    cf = without_operator(trace([src, rr, flt], ["pii_filter"]), "rerank")
    assert docs(_find_final_span(cf).outputs) == [("d1", 1), ("d2", 2)]


def test_passthrough_removal_recomputes_fuse_child_with_rrf_k_key() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"])])
    flt = span("filter", "FILTER", ["src"], [C("d1", 1, 1.0, ["src"])], inputs=src.outputs)
    dense = span("dense", "SOURCE", [], [C("d2", 1, 0.8, ["dense"])])
    fuse = span("fuse", "FUSE", ["filter", "dense"], [C("d1", 1, 0.5, ["src"]), C("d2", 2, 0.4, ["dense"])],
                params={"rrf_k": 1}, input_groups={"filter": flt.outputs, "dense": dense.outputs})
    t = trace([src, flt, dense, fuse], ["fuse"])

    assert replay_assumptions(t, "src").rrf_k is None  # src has no FUSE child
    cf = without_operator(t, "filter")
    fused = {c.doc_id: c for c in cf.span("fuse").outputs}
    # arms are [d1, d2] (filter's inputs) and [d2]; with rrf_k=1: d2 = 1/3 + 1/2, d1 = 1/2
    assert fused["d2"].score == pytest.approx(1 / 3 + 1 / 2)
    assert fused["d1"].score == pytest.approx(1 / 2)
    assert docs(cf.span("fuse").outputs) == [("d2", 1), ("d1", 2)]


def test_replay_assumptions_reads_rrf_k_param() -> None:
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"])])
    b = span("dense", "SOURCE", [], [C("d2", 1, 0.9, ["dense"])])
    fuse = span("fuse", "FUSE", ["bm25", "dense"], [C("d1", 1, 0.5, ["bm25"]), C("d2", 2, 0.4, ["dense"])], params={"rrf_k": 7})
    assert replay_assumptions(trace([a, b, fuse], ["fuse"]), "bm25").rrf_k == 7


def test_fuse_recompute_surfacing_unseen_doc_to_grandchild_is_indeterminate() -> None:
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"])])
    b = span("dense", "SOURCE", [], [C("d2", 1, 0.9, ["dense"]), C("d9", 2, 0.1, ["dense"])])
    fuse = span("fuse", "FUSE", ["bm25", "dense"], [C("d1", 1, 0.5, ["bm25"]), C("d2", 2, 0.4, ["dense"])],
                params={"rrf_k": 60}, input_groups={"bm25": a.outputs, "dense": b.outputs})
    rr = span("rerank", "RERANK", ["fuse"], [C("d2", 1, 5.0, ["dense"]), C("d1", 2, 4.0, ["bm25"])],
              policy="OBSERVED_ABLATION", inputs=fuse.outputs)
    result = simulate_without_operator(trace([a, b, fuse, rr], ["rerank"]), "bm25")
    assert result.status == "indeterminate"
    assert "rerank" in result.reason


# --- bug 2: multi-parent passthrough target ---


def _two_arm_rerank(shared_doc: bool):
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"]), C("d2", 2, 0.9, ["bm25"])])
    dense_docs = [C("d1", 1, 0.8, ["dense"]), C("d4", 2, 0.7, ["dense"])] if shared_doc else [C("d3", 1, 0.8, ["dense"]), C("d4", 2, 0.7, ["dense"])]
    b = span("dense", "SOURCE", [], dense_docs)
    return a, b


def test_multi_parent_rerank_removal_dedupes_and_renumbers_inputs() -> None:
    a, b = _two_arm_rerank(shared_doc=True)
    rr = span("rerank", "RERANK", ["bm25", "dense"], [C("d1", 1, 5.0, ["bm25", "dense"]), C("d4", 2, 4.0, ["dense"]), C("d2", 3, 3.0, ["bm25"])],
              policy="OBSERVED_ABLATION", input_groups={"bm25": a.outputs, "dense": b.outputs})
    trunc = span("truncate", "FILTER", ["rerank"], [C("d1", 1, 5.0, ["bm25", "dense"])], inputs=rr.outputs)
    t = trace([a, b, rr, trunc], ["truncate"])

    cf = without_operator(t, "rerank")
    assert docs(cf.span("truncate").outputs) == [("d1", 1)]
    assert cf.span("truncate").parent_ids == ("bm25", "dense")
    assert simulate_without_operator(t, "rerank").status == "replayed"
    rows = operator_marginal_contribution([t], "rerank", {"q1": {"d1": 1}})
    assert rows[0].result_status == "replayed"


def test_multi_parent_leaf_rerank_removal_does_not_raise() -> None:
    a, b = _two_arm_rerank(shared_doc=False)
    rr = span("rerank", "RERANK", ["bm25", "dense"], [C("d3", 1, 5.0, ["dense"]), C("d1", 2, 4.0, ["bm25"])],
              policy="OBSERVED_ABLATION", input_groups={"bm25": a.outputs, "dense": b.outputs})
    cf = without_operator(trace([a, b, rr], ["rerank"]), "rerank")
    assert set(cf.final_op_ids) == {"bm25", "dense"}


# --- bug 3 / bug 7b: SOURCE removal without (or beside) a FUSE child ---


def test_source_removal_keeps_docs_found_by_another_arm() -> None:
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"]), C("d2", 2, 0.9, ["bm25"])])
    b = span("dense", "SOURCE", [], [C("d1", 1, 0.8, ["dense"]), C("d3", 2, 0.7, ["dense"])])
    rr = span("rerank", "RERANK", ["bm25", "dense"],
              [C("d1", 1, 5.0, ["bm25", "dense"]), C("d3", 2, 4.0, ["dense"]), C("d2", 3, 3.0, ["bm25"])],
              policy="OBSERVED_ABLATION", input_groups={"bm25": a.outputs, "dense": b.outputs})
    cf = without_operator(trace([a, b, rr], ["rerank"]), "bm25")
    assert docs(cf.span("dense").outputs) == [("d1", 1), ("d3", 2)]
    assert docs(cf.span("rerank").outputs) == [("d1", 1), ("d3", 2)]


def test_source_removal_only_touches_descendants() -> None:
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"])])
    ra = span("rerank_a", "RERANK", ["bm25"], [C("d1", 1, 5.0, ["bm25"])], policy="OBSERVED_ABLATION", inputs=a.outputs)
    b = span("dense", "SOURCE", [], [C("d1", 1, 0.8, ["dense"])])
    rb = span("rerank_b", "RERANK", ["dense"], [C("d1", 1, 5.0, ["dense"])], policy="OBSERVED_ABLATION", inputs=b.outputs)
    cf = without_operator(trace([a, ra, b, rb], ["rerank_a", "rerank_b"]), "bm25")
    assert docs(cf.span("rerank_a").outputs) == []
    assert docs(cf.span("dense").outputs) == [("d1", 1)]
    assert docs(cf.span("rerank_b").outputs) == [("d1", 1)]


def test_source_feeding_fuse_and_direct_child_handles_both() -> None:
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"])])
    b = span("dense", "SOURCE", [], [C("d2", 1, 0.9, ["dense"])])
    fuse = span("fuse", "FUSE", ["bm25", "dense"], [C("d1", 1, 0.5, ["bm25"]), C("d2", 2, 0.4, ["dense"])],
                params={"rrf_k": 60}, input_groups={"bm25": a.outputs, "dense": b.outputs})
    direct = span("direct", "RERANK", ["bm25"], [C("d1", 1, 5.0, ["bm25"])], policy="OBSERVED_ABLATION", inputs=a.outputs)
    cf = without_operator(trace([a, b, fuse, direct], ["fuse", "direct"]), "bm25")
    assert docs(cf.span("fuse").outputs) == [("d2", 1)]
    assert docs(cf.span("direct").outputs) == []


def test_source_to_fuse_arm_removal_regression_guard() -> None:
    """Exactly the pre-existing SOURCE->FUSE behaviour: arm dropped, RRF re-run over the rest."""
    a = span("arm_bm25", "SOURCE", [], [C("d1", 1, 1.0, ["arm_bm25"]), C("d2", 2, 0.5, ["arm_bm25"])])
    b = span("arm_dense", "SOURCE", [], [C("d2", 1, 0.9, ["arm_dense"]), C("d3", 2, 0.8, ["arm_dense"])], policy="NOT_REPLAYABLE")
    fuse = span("fuse_rrf", "FUSE", ["arm_bm25", "arm_dense"],
                [C("d2", 1, 2.0, ["arm_bm25", "arm_dense"]), C("d1", 2, 1.0, ["arm_bm25"]), C("d3", 3, 0.8, ["arm_dense"])],
                params={"k": 60})
    cf = without_operator(trace([a, b, fuse], ["fuse_rrf"]), "arm_bm25")
    assert [s.op_id for s in cf.spans] == ["arm_dense", "fuse_rrf"]
    fused = cf.span("fuse_rrf")
    assert fused.parent_ids == ("arm_dense",)
    assert docs(fused.outputs) == [("d2", 1), ("d3", 2)]
    assert [c.score for c in fused.outputs] == pytest.approx([1 / 61, 1 / 62])
    assert all(c.origin_op_ids == ("arm_dense",) for c in fused.outputs)
    assert all(c.add_reason == "fused" and c.decision_evidence == "legacy_inferred" for c in fused.outputs)


# --- bug 4: EXPAND must not mark pass-through rows as expanded ---


def _expand_trace():
    src_out = (C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"]))
    tr = build_candidate_transition(
        input_groups={"src": src_out},
        output_items=[Document("d1", "", 1.0, 1), Document("d2", "", 0.9, 2), Document("neighbor", "", 0.5, 3)],
        op_id="expand", op_type="EXPAND",
    )
    src = span("src", "SOURCE", [], src_out)
    ex = span("expand", "EXPAND", ["src"], tr.outputs, input_groups={"src": tr.input_groups["src"]})
    return src, ex


def test_expand_transition_stamps_expanded_only_on_introduced_rows() -> None:
    _, ex = _expand_trace()
    by_doc = {c.doc_id: c for c in ex.outputs}
    assert by_doc["d1"].add_reason == "retrieved"
    assert by_doc["d2"].add_reason == "retrieved"
    assert by_doc["neighbor"].add_reason == "expanded"
    assert by_doc["neighbor"].origin_op_ids == ("expand",)


def test_expand_removal_keeps_passthrough_docs_through_child_rerank() -> None:
    src, ex = _expand_trace()
    tr2 = build_candidate_transition(
        input_groups={"expand": ex.outputs},
        output_items=[Document("d1", "", 5.0, 1), Document("neighbor", "", 4.0, 2), Document("d2", "", 3.0, 3)],
        op_id="rerank", op_type="RERANK",
    )
    rr = span("rerank", "RERANK", ["expand"], tr2.outputs, input_groups={"expand": tr2.input_groups["expand"]}, policy="OBSERVED_ABLATION")
    cf = without_operator(trace([src, ex, rr], ["rerank"]), "expand")
    assert docs(_find_final_span(cf).outputs) == [("d1", 1), ("d2", 2)]
    assert _metric_at_k([c.doc_id for c in _find_final_span(cf).outputs], {"d1": 1}, "recall", 10) == 1.0


# --- bug 5: candidate history and miss attribution across gated / fan-out branches ---


def _gated_trace():
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"])])
    gate = span("gate", "GATE", ["src"], src.outputs, inputs=src.outputs, gate_values={"selected_route": "a"})
    br_a = span("branch_a", "FILTER", ["gate"], src.outputs, inputs=gate.outputs)
    br_b = span("branch_b", "RERANK", ["gate"], [], status="SKIPPED_BY_GATE", policy="OBSERVED_ABLATION")
    merge = span("merge", "TRANSFORM", ["branch_a", "branch_b"], [C("d2", 1, 0.9, ["src"]), C("d1", 2, 1.0, ["src"])],
                 input_groups={"branch_a": br_a.outputs, "branch_b": ()})
    return trace([src, gate, br_a, br_b, merge], ["merge"])


def test_candidate_history_ignores_skipped_branch() -> None:
    h = candidate_history(_gated_trace(), "d1")
    assert h.introduced_at == "src"
    assert h.survived is True and h.final_rank == 2
    assert [(e.op_id, e.event) for e in h.events] == [
        ("src", "introduced"), ("gate", "passed"), ("branch_a", "passed"), ("merge", "passed"),
    ]


@pytest.mark.asyncio
async def test_attribute_miss_ignores_skipped_branch() -> None:
    misses = await attribute_miss(_gated_trace(), {"q1": {"d1": 1}}, k=1)
    assert [(m.doc_id, m.miss_type, m.op_id) for m in misses] == [("d1", "ranked_below_k", None)]


def test_candidate_history_fan_out_keeps_first_introduction() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"])])
    fa = span("filter_a", "FILTER", ["src"], [], inputs=src.outputs)
    fb = span("filter_b", "FILTER", ["src"], src.outputs, inputs=src.outputs)
    h = candidate_history(trace([src, fa, fb], ["filter_b"]), "d1")
    assert h.introduced_at == "src"
    assert h.survived is True and h.dropped_at is None
    assert [(e.op_id, e.event) for e in h.events] == [("src", "introduced"), ("filter_a", "dropped"), ("filter_b", "passed")]
    assert "does not reach the final output" in h.events[1].note


# --- bug 6: clipped strings are not partial lineage ---


def test_truncated_strings_do_not_make_lineage_partial() -> None:
    big = "x" * 9000
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"], metadata={"text": big}), C("d2", 2, 0.9, ["src"], metadata={"text": "short"})])
    flt = span("filter", "FILTER", ["src"], [C("d1", 1, 1.0, ["src"], metadata={"text": big})], inputs=[
        C("d1", 1, 1.0, ["src"], metadata={"text": big}),
        C("d2", 2, 0.9, ["src"], metadata={"text": "short"}, drop_reason="filtered", decision_reason="filtered", decision_evidence="recorded"),
    ])
    normalized = normalize_trace(trace([src, flt], ["filter"]), limits=PayloadLimits(), redacted_keys=frozenset())
    assert normalized.report.truncated_strings == 3
    assert normalized.report.omitted_fields == 0
    assert normalized.payload["capture"]["truncated_string_count"] == 3
    assert normalized.payload["capture"]["omitted_field_count"] == 0

    rt = RetrievalTrace.from_dict(normalized.payload)
    assert rt.capture.truncated_string_count == 3
    graph = build_candidate_lineage(rt, qrels_for_query={"d1": 1, "d2": 0}, qrel_chunk_mapping_complete=True)
    assert graph.candidates["d1"].lineage_evidence == "recorded"
    assert graph.candidates["d1"].outcome.evidence == "recorded"
    assert graph.candidates["d2"].removed_at == "filter"
    history = candidate_history(rt, "d2")
    assert history.dropped_at == "filter"
    assert history.lineage_evidence == "recorded"


def test_capture_metadata_without_truncated_string_count_is_backward_compatible() -> None:
    capture = CaptureMetadata(**{"omitted_field_count": 2})
    assert capture.truncated_string_count == 0
    assert capture.omitted_field_count == 2


# --- bug 8: serialization and rank renumbering ---


def test_from_dict_reads_legacy_final_op_id() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"])])
    payload = trace([src], ["src"]).to_dict()
    payload.pop("final_op_ids")
    payload["final_op_id"] = "src"
    assert RetrievalTrace.from_dict(payload).final_op_ids == ("src",)


def test_descendant_ranks_are_renumbered_after_fuse_arm_removal() -> None:
    a = span("bm25", "SOURCE", [], [C("d1", 1, 1.0, ["bm25"]), C("d5", 2, 0.5, ["bm25"])])
    b = span("dense", "SOURCE", [], [C("d2", 1, 0.9, ["dense"]), C("d3", 2, 0.8, ["dense"])])
    fuse = span("fuse", "FUSE", ["bm25", "dense"],
                [C("d1", 1, 0.5, ["bm25"]), C("d2", 2, 0.4, ["dense"]), C("d5", 3, 0.3, ["bm25"]), C("d3", 4, 0.2, ["dense"])],
                params={"rrf_k": 60}, input_groups={"bm25": a.outputs, "dense": b.outputs})
    rr = span("rerank", "RERANK", ["fuse"],
              [C("d5", 1, 5.0, ["bm25"]), C("d2", 2, 4.0, ["dense"]), C("d1", 3, 3.0, ["bm25"]), C("d3", 4, 2.0, ["dense"])],
              policy="OBSERVED_ABLATION", inputs=fuse.outputs)
    cf = without_operator(trace([a, b, fuse, rr], ["rerank"]), "bm25")
    final = _find_final_span(cf)
    assert docs(final.outputs) == [("d2", 1), ("d3", 2)]
    assert [c.output_rank for c in final.outputs] == [1, 2]


# --- bug 9: leaf target must not spill onto an unrelated span ---


def test_leaf_filter_removal_does_not_touch_unrelated_span() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"])])
    flt = span("filter", "FILTER", ["src"], [C("d1", 1, 1.0, ["src"])], inputs=src.outputs)
    other = span("other_src", "SOURCE", [], [C("z9", 1, 0.3, ["other_src"])])
    cf = without_operator(trace([src, flt, other], ["filter", "other_src"]), "filter")
    assert docs(cf.span("other_src").outputs) == [("z9", 1)]
    assert docs(cf.span("src").outputs) == [("d1", 1), ("d2", 2)]
    assert set(cf.final_op_ids) == {"src", "other_src"}


# --- bug 7a: Benjamini-Hochberg across operators ---


def _chain_traces(n: int):
    traces, qrels = [], {}
    for i in range(n):
        src = span("src", "SOURCE", [], [C("gold", 1, 1.0, ["src"]), C("x", 2, 0.5, ["src"])])
        fa = span("f_a", "FILTER", ["src"], src.outputs, inputs=src.outputs)
        fb = span("f_b", "FILTER", ["f_a"], fa.outputs, inputs=fa.outputs)
        fc = span("f_c", "FILTER", ["f_b"], fb.outputs, inputs=fb.outputs)
        traces.append(trace([src, fa, fb, fc], ["f_c"], tid=f"t{i}", qid=f"q{i}"))
        qrels[f"q{i}"] = {"gold": 1}
    return traces, qrels


def test_plural_contributions_apply_bh_across_operators(monkeypatch: pytest.MonkeyPatch) -> None:
    traces, qrels = _chain_traces(3)
    scripted = iter([0.03, 0.5, 0.8])
    monkeypatch.setattr(attribution, "paired_bootstrap_test", lambda *a, **kw: next(scripted))

    single = operator_marginal_contribution(traces, "f_a", qrels, metric="mrr", k=10, n_power_threshold=2, n_bootstrap=10)
    assert single[0].p_value == 0.03 and single[0].q_value == pytest.approx(0.03) and single[0].significant is True

    scripted = iter([0.03, 0.5, 0.8])
    rows = operator_marginal_contributions(
        traces, ["f_a", "f_b", "f_c"], qrels, metric="mrr", k=10, n_power_threshold=2, n_bootstrap=10,
    )
    by_op = {row.op_id: row for row in rows}
    assert [row.op_id for row in rows] == ["f_a", "f_b", "f_c"]
    assert all(row.result_status == "replayed" for row in rows)
    assert by_op["f_a"].p_value == 0.03
    assert by_op["f_a"].q_value == pytest.approx(0.09)
    assert by_op["f_a"].significant is False
    assert by_op["f_c"].q_value == pytest.approx(0.8)


# --- a removed final operator hands its terminal role only to parents that fired ---


def test_removing_a_final_operator_hands_terminal_role_to_fired_parents_only() -> None:
    src = span("src", "SOURCE", [], [C("d1", 1, 1.0, ["src"]), C("d2", 2, 0.9, ["src"])])
    gate = span("gate", "GATE", ["src"], src.outputs, inputs=src.outputs, gate_values={"selected_route": "rerank"})
    fast = span("fast", "TRANSFORM", ["gate"], [], status="SKIPPED_BY_GATE", policy="OBSERVED_ABLATION")
    rerank = span(
        "rerank", "RERANK", ["gate"], [C("d2", 1, 0.9, ["src"]), C("d1", 2, 1.0, ["src"])],
        policy="OBSERVED_ABLATION", inputs=gate.outputs,
    )
    final = span("final", "FUSE", ["fast", "rerank"], rerank.outputs, input_groups={"fast": (), "rerank": rerank.outputs})
    t = trace([src, gate, fast, rerank, final], ["final"])

    cf = without_operator(t, "final")
    # Previously ("fast", "rerank"): the skipped branch, with no outputs, was scored as the final list.
    assert cf.final_op_ids == ("rerank",)
    assert [c.doc_id for c in _find_final_span(cf).outputs] == ["d2", "d1"]
    rows = operator_marginal_contribution([t], "final", {"q1": {"d2": 1}}, metric="ndcg", k=10)
    assert [(r.result_status, r.delta) for r in rows] == [("replayed", 0.0)]
