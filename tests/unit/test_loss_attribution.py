"""Loss attribution: PREREGISTRATION.md §3 definitions and §3.11 mandated cases."""
from __future__ import annotations

from dataclasses import replace

from retrieval_observatory.analysis.loss_attribution import (
    OPERATOR_CLASSES,
    GoldEvent,
    attribute_run,
    gold_events,
    operator_class,
    self_inflicted_difference,
    summarize,
)
from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import CaptureMetadata, Candidate, OperatorSpan, RetrievalTrace, TraceTiming

G = "gold"


def _docs(n: int, gold_at: int | None) -> list[str]:
    """`n` doc ids with the gold at 1-based position `gold_at` (None = absent)."""
    ids = [f"d{i}" for i in range(1, n + 1)]
    if gold_at is not None:
        ids[gold_at - 1] = G
    return ids


def _cands(ids: list[str]) -> list[Candidate]:
    return [Candidate(doc_id=d, score=1.0 / r, rank=r) for r, d in enumerate(ids, start=1)]


def _span(op_id: str, op_type: str, parents: list[str], outputs: list[str], inputs: dict[str, list[str]] | None = None, status="FIRED"):
    return OperatorSpan(
        op_id=op_id, op_type=op_type, op_name=op_id, parent_ids=tuple(parents), status=status, latency_ms=1.0,
        input_groups={p: tuple(_cands(ids)) for p, ids in (inputs or {}).items()},
        outputs=tuple(_cands(outputs)) if status == "FIRED" else (),
    )


def _trace(*spans: OperatorSpan, finals: tuple[str, ...] = (), status="OK", capture=None, query_id="q1") -> RetrievalTrace:
    return RetrievalTrace(
        trace_id="t", service_id="svc", run_id="run", query_id=query_id, query_text="?", pipeline_id="p",
        spans=tuple(spans), final_op_ids=finals or (spans[-1].op_id,), status=status,
        timing=TraceTiming(1.0, 1.0, 1.0), capture=capture or CaptureMetadata(),
    )


def _chain(*stages: tuple[str, str, list[str]]) -> RetrievalTrace:
    """Linear pipeline; each span's single input group is the previous span's outputs."""
    spans: list[OperatorSpan] = []
    previous: tuple[str, list[str]] | None = None
    for op_id, op_type, outputs in stages:
        inputs = {previous[0]: previous[1]} if previous else None
        spans.append(_span(op_id, op_type, [previous[0]] if previous else [], outputs, inputs))
        previous = (op_id, outputs)
    return _trace(*spans)


def _one(trace: RetrievalTrace) -> GoldEvent:
    return gold_events(trace, [G])[0]


# --- §3.11 mandated cases -------------------------------------------------------------


def test_rerank_moves_gold_from_6_to_14_then_truncate_blames_rerank():
    trace = _chain(("source", "SOURCE", _docs(20, 6)), ("rerank", "RERANK", _docs(20, 14)))
    event = _one(trace)
    assert event.outcome == "destroyed"
    assert event.last_displacer.op_id == "rerank" and event.first_displacer.op_id == "rerank"
    assert event.last_displacer.operator_class == "rerank"
    assert event.recoveries == 0 and event.redisplacements == 0


def test_fusion_lifts_gold_from_30_to_4_then_filter_removes_it_blames_filter():
    bm25 = _span("bm25", "SOURCE", [], _docs(40, 30))
    dense = _span("dense", "SOURCE", [], _docs(40, None))
    fuse = _span("fuse", "FUSE", ["bm25", "dense"], _docs(40, 4), {"bm25": _docs(40, 30), "dense": _docs(40, None)})
    filt = _span("filter", "FILTER", ["fuse"], _docs(39, None), {"fuse": _docs(40, 4)})
    event = _one(_trace(bm25, dense, fuse, filt))
    assert event.outcome == "destroyed"
    assert event.last_displacer.op_id == "filter" and event.last_displacer.operator_class == "filter/dedup"
    # Fusion moved the gold *into* the window from outside; nothing had displaced it, so no recovery.
    assert event.recoveries == 0


def test_displaced_then_recovered_then_removed_counts_recovery_and_redisplacement():
    trace = _chain(
        ("source", "SOURCE", _docs(40, 6)),
        ("boost", "BOOST", _docs(40, 15)),      # displaced (first)
        ("fuse", "FUSE", _docs(40, 4)),         # recovered
        ("filter", "FILTER", _docs(39, None)),  # re-displaced (last)
    )
    event = _one(trace)
    assert event.outcome == "destroyed"
    assert event.first_displacer.op_id == "boost" and event.last_displacer.op_id == "filter"
    assert event.displacements == 2 and event.recoveries == 1 and event.redisplacements == 1


def test_gold_never_above_rank_40_is_surfaced_never_in_window():
    trace = _chain(("source", "SOURCE", _docs(100, 45)), ("rerank", "RERANK", _docs(100, 41)))
    event = _one(trace)
    assert event.outcome == "surfaced_never_in_window"
    assert event.surfaced and not event.ever_in_window
    assert event.surfaced_within_fixed_k  # rank 41 is within K=50
    assert event.first_displacer is None


def test_gold_only_beyond_fixed_k_is_not_surfaced_under_the_variant():
    event = _one(_chain(("source", "SOURCE", _docs(100, 60))))
    assert event.outcome == "surfaced_never_in_window"
    assert not event.surfaced_within_fixed_k


def test_gold_absent_everywhere_is_never_surfaced():
    event = _one(_chain(("source", "SOURCE", _docs(20, None)), ("rerank", "RERANK", _docs(20, None))))
    assert event.outcome == "never_surfaced"
    assert not event.surfaced and event.last_displacer is None


def test_single_operator_control_cannot_destroy():
    assert _one(_chain(("bm25", "SOURCE", _docs(100, 3)))).outcome == "delivered"
    assert _one(_chain(("bm25", "SOURCE", _docs(100, 15)))).outcome == "surfaced_never_in_window"
    assert _one(_chain(("bm25", "SOURCE", _docs(100, None)))).outcome == "never_surfaced"


def test_multi_parent_fuse_window_is_met_through_one_parent_only():
    bm25 = _span("bm25", "SOURCE", [], _docs(100, 2))
    dense = _span("dense", "SOURCE", [], _docs(100, 40))
    fuse = _span("fuse", "FUSE", ["bm25", "dense"], _docs(100, 12), {"bm25": _docs(100, 2), "dense": _docs(100, 40)})
    event = _one(_trace(bm25, dense, fuse))
    assert event.outcome == "destroyed"
    assert event.last_displacer.op_id == "fuse" and event.last_displacer.operator_class == "fusion"


# --- Structure: final cut, gates, branches, exclusions --------------------------------


def test_final_top_k_cut_is_never_a_destroyer():
    # Gold at final rank 14: the operator that moved it past 10 is blamed, not the cut.
    trace = _chain(("source", "SOURCE", _docs(50, 3)), ("fuse", "FUSE", _docs(50, 14)), ("gate", "GATE", _docs(50, 14)))
    event = _one(trace)
    assert event.outcome == "destroyed" and event.last_displacer.op_id == "fuse"


def test_gate_passthrough_and_skipped_branch_are_ignored():
    source = _span("source", "SOURCE", [], _docs(40, 5))
    gate = _span("gate", "GATE", ["source"], _docs(40, 5), {"source": _docs(40, 5)})
    skipped = _span("widen", "EXPAND", ["gate"], [], status="SKIPPED_BY_GATE")
    fired = _span("hop2", "EXPAND", ["gate"], _docs(58, 12), {"gate": _docs(40, 5)})
    event = _one(_trace(source, gate, skipped, fired, finals=("hop2",)))
    assert event.outcome == "destroyed"
    assert event.last_displacer.op_id == "hop2" and event.last_displacer.operator_class == "expand"


def test_in_window_on_a_branch_that_never_reaches_the_final_is_unattributed():
    source = _span("source", "SOURCE", [], _docs(40, 30))
    side = _span("side", "BOOST", ["source"], _docs(40, 2), {"source": _docs(40, 30)})
    main = _span("main", "RERANK", ["source"], _docs(40, 30), {"source": _docs(40, 30)})
    event = _one(_trace(source, side, main, finals=("main",)))
    assert event.outcome == "unattributed"


def test_set_level_refind_is_recorded_separately_from_recovery():
    # Scenario D shape: dense rank 27 → cut by fusion → re-found by expand at 45.
    trace = _chain(("dense", "SOURCE", _docs(30, 27)), ("fuse", "FUSE", _docs(40, None)), ("hop2", "EXPAND", _docs(58, 45)))
    event = _one(trace)
    assert event.outcome == "surfaced_never_in_window"
    assert event.set_refound and event.recoveries == 0


def test_attribute_run_excludes_failed_and_partial_traces_and_reports_completeness():
    ok = _chain(("source", "SOURCE", _docs(20, 3)))
    failed = replace(_chain(("source", "SOURCE", _docs(20, 3))), query_id="q2", status="ERROR")
    partial = replace(
        _chain(("source", "SOURCE", _docs(20, 3))), query_id="q3", capture=CaptureMetadata(omitted_field_count=2)
    )
    qrels = {"q1": {G: 1, "d9": 0}, "q2": {G: 1}, "q3": [G, "d2"], "q4": {G: 1}}
    run = attribute_run([ok, failed, partial], qrels)
    assert [e.outcome for e in run.events] == ["delivered"]
    assert [(x.query_id, x.gold_count) for x in run.excluded] == [("q2", 1), ("q3", 2)]
    assert run.completeness == 1 / 4


def test_runner_recorded_ranks_are_read_through_the_transition_builder():
    # The runner clones inputs with input_rank/output_rank set; those must drive the window test.
    source_out = _cands(_docs(30, 6))
    transition = build_candidate_transition(
        input_groups={"source": source_out},
        output_items=_cands(_docs(30, 14)),
        op_id="rerank",
        op_type="RERANK",
    )
    rerank = OperatorSpan(
        op_id="rerank", op_type="RERANK", op_name="rerank", parent_ids=("source",), status="FIRED", latency_ms=1.0,
        input_groups=transition.input_groups, outputs=transition.outputs,
    )
    gold_in = next(c for c in rerank.input_groups["source"] if c.doc_id == G)
    assert gold_in.input_rank == 6 and gold_in.output_rank == 14
    event = _one(_trace(_span("source", "SOURCE", [], _docs(30, 6)), rerank))
    assert event.outcome == "destroyed" and event.last_displacer.op_id == "rerank"


# --- Summary statistics ---------------------------------------------------------------


def _event(query_id: str, outcome: str, displacer: str | None = None, cls: str | None = None, **extra) -> GoldEvent:
    from retrieval_observatory.analysis.loss_attribution import Displacement

    disp = Displacement(displacer, "X", cls) if displacer else None
    return GoldEvent(
        query_id=query_id, doc_id="g", outcome=outcome, surfaced=outcome != "never_surfaced",
        surfaced_within_fixed_k=outcome not in {"never_surfaced"}, ever_in_window=outcome in {"delivered", "destroyed"},
        first_displacer=disp, last_displacer=disp, displacements=1 if disp else 0, **extra,
    )


def test_summary_fractions_and_shares():
    events = [
        _event("q1", "delivered"),
        _event("q1", "destroyed", "fuse", "fusion"),
        _event("q2", "destroyed", "rerank", "rerank", recoveries=1, redisplacements=1),
        _event("q2", "never_surfaced"),
        _event("q3", "surfaced_never_in_window"),
        _event("q3", "destroyed", "fuse", "fusion"),
    ]
    summary = summarize(events, n_resamples=200, seed=17)
    assert summary.n_queries == 3 and summary.n_pairs == 6
    assert summary.outcome_counts["destroyed"] == 3 and summary.outcome_counts["delivered"] == 1
    # 3 destroyed of 5 misses; delivered golds are not in the denominator.
    assert summary.self_inflicted_fraction.value == 3 / 5
    assert summary.self_inflicted_fraction.numerator == 3 and summary.self_inflicted_fraction.denominator == 5
    assert summary.never_surfaced_fraction.value == 1 / 5
    assert summary.loss_share_by_class["fusion"].value == 2 / 3
    assert summary.loss_share_by_class["rerank"].value == 1 / 3
    assert summary.loss_share_by_class["expand"].value == 0.0
    assert set(summary.loss_share_by_class) == set(OPERATOR_CLASSES)
    assert summary.loss_share_by_operator["fuse"].value == 2 / 3
    assert summary.recovery_rate.value == 1 / 3 and summary.redisplacement_rate.value == 1.0
    low, high = summary.self_inflicted_fraction.ci_low, summary.self_inflicted_fraction.ci_high
    assert low <= 3 / 5 <= high
    assert summary.to_dict()["self_inflicted_fraction"]["value"] == 3 / 5


def test_summary_with_no_misses_reports_undefined_rates():
    summary = summarize([_event("q1", "delivered")], n_resamples=10)
    assert summary.self_inflicted_fraction.value is None
    assert summary.self_inflicted_fraction.denominator == 0
    assert summary.recovery_rate.value is None


def test_bootstrap_is_deterministic_for_a_seed():
    events = [_event(f"q{i}", "destroyed" if i % 3 else "never_surfaced", "fuse", "fusion") for i in range(30)]
    first = summarize(events, n_resamples=300, seed=17).self_inflicted_fraction
    second = summarize(events, n_resamples=300, seed=17).self_inflicted_fraction
    assert (first.ci_low, first.ci_high) == (second.ci_low, second.ci_high)
    assert first.ci_low < first.value < first.ci_high


def test_self_inflicted_difference_is_paired_on_shared_queries():
    a = [_event("q1", "destroyed", "fuse", "fusion"), _event("q2", "never_surfaced"), _event("q3", "never_surfaced")]
    b = [_event("q1", "destroyed", "rerank", "rerank"), _event("q2", "destroyed", "rerank", "rerank"), _event("q9", "delivered")]
    diff, dropped = self_inflicted_difference(a, b, n_resamples=200)
    assert dropped == 2  # q3 only in a, q9 only in b
    assert diff.value == 1.0 - 0.5
    same, _ = self_inflicted_difference(a, a, n_resamples=50)
    assert same.value == 0.0 and (same.ci_low, same.ci_high) == (0.0, 0.0)


def test_operator_class_mapping_is_by_op_type():
    assert operator_class("FUSE") == "fusion"
    assert operator_class("GATE") == "routing/merge"
    assert operator_class("EXPAND") == "expand"
    assert operator_class("TRANSFORM") == "other"
    assert operator_class("SOURCE") == "other"
