"""A position is never a document id: an output whose items carry no id is recorded as unreadable,
``retobs evaluate`` refuses id-less results loudly, and a trace's final step is what the
entrypoint returned, never every step whose parent links happen to be missing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.metrics.comparison import rank_metric_keys
from retrieval_observatory.release.policy import ReleasePolicy, ReleasePolicyV3
from retrieval_observatory.release.resolution import RunEvidence, convert_v2_policy, resolve_policy
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace, trace_scope
from retrieval_observatory.sdk.report import _headline_metrics, build_run_report
from retrieval_observatory.sdk.wrappers import _normalize_documents
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing import BufferedTraceSink, MemoryExporter, TraceRecorder
from retrieval_observatory.tracing.candidates import UnreadableCandidates, build_candidate_transition, to_candidates
from retrieval_observatory.tracing.model import OperatorSpan, final_op_ids_of


def _items(*ids: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=doc_id, score=1.0) for doc_id in ids]


def test_one_id_less_item_makes_the_whole_output_unreadable() -> None:
    with pytest.raises(UnreadableCandidates, match="item 2 is a dict with no id"):
        to_candidates([{"id": "doc-a1"}, {"text": "no id here"}], "screen")
    with pytest.raises(UnreadableCandidates, match="item 1 is a list, not a candidate"):
        build_candidate_transition(input_groups={}, output_items=[_items("doc-a1"), [], [], False], op_id="screen", op_type="FILTER")
    for missing in (None, ""):
        with pytest.raises(UnreadableCandidates):
            to_candidates([{"id": missing}], "screen")


def test_strings_and_zero_are_ids() -> None:
    assert [c.doc_id for c in to_candidates(["doc-a1", "doc-b2"], "merge")] == ["doc-a1", "doc-b2"]
    found = to_candidates([{"id": 0}, {"doc_id": "", "id": "doc-c3"}, {"metadata": {"id": "doc-d4"}}], "merge")
    assert [c.doc_id for c in found] == ["0", "doc-c3", "doc-d4"]
    assert {c.identity_evidence for c in found} == {"recorded"}


def test_observed_step_returning_a_tuple_records_no_candidates() -> None:
    @observe("FILTER", op_id="screen_candidates")
    def screen_candidates(mode, rules, items):
        return items, [], [], False

    start_trace(ObserveContext(None, "q1", "alpha", "pipe"))
    screen_candidates("strict", {}, _items("doc-a1", "doc-b2"))
    trace = finish_trace()

    span = trace.span("screen_candidates")
    assert span.output_capture == "unavailable" and span.outputs == ()
    [failure] = trace.capture_failures
    assert (failure["op_id"], failure["phase"], failure["code"]) == ("screen_candidates", "outputs", "candidate_ids_missing")
    assert failure["detail"] == "returned tuple of 4 items; item 1 is a list, not a candidate"


def test_recorder_span_with_id_less_documents_is_unavailable_not_raised() -> None:
    recorder = TraceRecorder("svc", BufferedTraceSink(MemoryExporter(), service_id="svc"))
    context = recorder.start_trace("alpha", "pipe")
    context.span("SOURCE", "lookup", [SimpleNamespace(text="no id")], 1.0, op_id="lookup")
    trace = context.build_trace()
    recorder.finish(context)
    assert trace.span("lookup").output_capture == "unavailable" and trace.span("lookup").outputs == ()
    assert [failure["code"] for failure in trace.capture_failures] == ["candidate_ids_missing"]


def _span(op_id: str, parents: tuple[str, ...] = (), op_type: str = "TRANSFORM") -> OperatorSpan:
    return OperatorSpan(op_id, op_type, op_id, parents, "FIRED", 1.0, outputs=tuple(to_candidates(["doc-a1"], op_id)))


def test_unlinked_steps_have_one_final_step_and_linked_branches_keep_theirs() -> None:
    # No declared links: the last step that fired is the one final step, not all three.
    assert final_op_ids_of([_span("merge_lanes"), _span("screen_candidates"), _span("diversify")]) == ("diversify",)
    # Declared links that genuinely end in parallel terminal branches keep every terminal.
    assert final_op_ids_of([_span("source"), _span("lexical", ("source",)), _span("dense", ("source",))]) == ("lexical", "dense")
    # A gate's decision is never the answer, even when it fires last.
    assert final_op_ids_of([_span("source"), _span("rerank", ("source",)), _span("route", op_type="GATE")]) == ("rerank",)


def test_trace_scope_unreadable_return_chooses_the_final_step_by_order(tmp_path: Path) -> None:
    db = str(tmp_path / "scope.db")

    @observe("FUSE", op_id="merge_lanes")
    def merge_lanes(a, b):
        return _items(*a, *b)

    @observe("RERANK", op_id="diversify")
    def diversify(items):
        return items[::-1]

    @trace_scope("svc", "pipe", db_path=db)
    def retrieve(query):
        diversify(merge_lanes(["doc-a1"], ["doc-b2"]))
        return [SimpleNamespace(text="answer without ids")]

    retrieve("alpha")

    async def stored():
        store = SQLiteStore(db_path=db)
        await store.init_db()
        return await store.list_traces(TraceQuery(service_id="svc"))

    [trace] = asyncio.run(stored())
    assert trace.final_op_ids == ("diversify",)
    [failure] = trace.capture_failures
    assert failure["op_id"] == "return" and failure["code"] == "final_output_shape_unsupported"
    assert failure["detail"] == (
        "returned list of 1 items; item 1 is a SimpleNamespace with no id; final step diversify chosen by execution order"
    )


def test_evaluate_normalization_uses_the_candidate_id_rule() -> None:
    documents = _normalize_documents([*_items("doc-a1"), {"id": 0}, ("doc-b2", 0.5), "doc-c3"], corpus={"doc-a1": "alpha"})
    assert [(doc.id, doc.text) for doc in documents] == [("doc-a1", "alpha"), ("0", ""), ("doc-b2", ""), ("doc-c3", "")]
    with pytest.raises(TypeError, match="item 2 is a SimpleNamespace with no id"):
        _normalize_documents([*_items("doc-a1"), SimpleNamespace(text="no id")])
    with pytest.raises(TypeError, match="item 1 is a list with no id"):
        _normalize_documents((_items("doc-a1"), [], [], False))
    with pytest.raises(TypeError, match="item 1 is a dict with no id"):
        _normalize_documents([{"doc_id": None, "text": "no id"}])


def test_evaluate_fails_loudly_when_the_callable_returns_objects_without_ids(tmp_path: Path) -> None:
    target = tmp_path / "noid.py"
    target.write_text(
        "from types import SimpleNamespace\n"
        "def retrieve(query):\n"
        "    return [SimpleNamespace(title='alpha guide', score=1.0)]\n",
        encoding="utf-8",
    )
    (tmp_path / "queries.jsonl").write_text('{"query_id": "q1", "text": "alpha"}\n', encoding="utf-8")
    (tmp_path / "qrels.jsonl").write_text('{"query_id": "q1", "doc_id": "doc-a1", "relevance": 1}\n', encoding="utf-8")
    (tmp_path / "corpus.jsonl").write_text('{"doc_id": "doc-a1", "text": "alpha"}\n', encoding="utf-8")

    result = CliRunner().invoke(app, [
        "evaluate", f"{target}:retrieve", "--db", str(tmp_path / "results.db"),
        "--queries", str(tmp_path / "queries.jsonl"), "--qrels", str(tmp_path / "qrels.jsonl"),
        "--corpus", str(tmp_path / "corpus.jsonl"),
    ])

    assert result.exit_code == 1
    assert (
        "TypeError: the callable returned list of 1 items; item 1 is a SimpleNamespace with no id. "
        "Return ids, (id, score) pairs, dicts with id or doc_id, or objects with an id attribute."
    ) in result.stdout
    assert "namespace(" not in result.stdout


def _metric(stage: int, name: str, branch: str | None, mean: float) -> tuple[str, dict]:
    key = f"pipe|stage{stage}|{name}@10" + (f"|branch={branch}" if branch else "")
    return key, {"pipeline_id": "pipe", "stage_index": stage, "metric_name": name, "k": 10, "branch_id": branch, "mean": mean}


# Unlinked steps share stage 0 as branches; stage -1 holds each question's own final answer.
UNLINKED = dict([_metric(0, "recall", "a_merge", 0.2), _metric(0, "recall", "z_final", 0.9)])
FINAL = "pipe|stage-1|recall@10"


def test_headline_reads_each_questions_final_answer() -> None:
    assert list(_headline_metrics({**UNLINKED, FINAL: _metric(-1, "recall", None, 0.9)[1]})) == [FINAL]
    # A run scored before final-answer rows existed keeps the terminal-stage rule.
    assert list(_headline_metrics(UNLINKED)) == ["pipe|stage0|recall@10|branch=a_merge"]


def test_comparison_ranks_the_final_answer_first() -> None:
    assert rank_metric_keys([*UNLINKED, FINAL])[0] == FINAL


def _rows(run_id: str) -> list[dict]:
    rows = []
    for query_id in ("q1", "q2"):
        for stage, branch in ((0, "a_merge"), (0, "z_final"), (-1, None)):
            rows.append({
                "run_id": run_id, "pipeline_id": "pipe", "query_id": query_id, "stage_index": stage,
                "metric_name": "recall", "k": 10, "value": 1.0, "branch_id": branch, "query_metadata": {},
            })
    return rows


def test_release_final_retrieval_reads_each_questions_final_answer() -> None:
    runs = [RunEvidence(run, {"normalized_config": {"pipelines": [{"id": "pipe"}]}}, _rows(run)) for run in ("base", "cand")]
    policy = ReleasePolicyV3.model_validate({
        "schema_version": 3, "id": "final", "evaluation": {"unit": "document", "k": 10},
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 1},
        "metrics": [{"id": "final-recall", "metric": "recall", "target": "final_retrieval", "direction": "higher_is_better",
                     "max_regression": 0.01, "min_paired_n": 2}],
    })
    [check] = resolve_policy(policy, *runs).checks
    assert check.status == "resolved" and check.metric_key_by_run == {"base": FINAL, "cand": FINAL}

    legacy = ReleasePolicy.model_validate({
        "id": "final", "schema_version": 2,
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 1},
        "metrics": [{"metric": FINAL, "direction": "higher_is_better", "max_regression": 0.01, "min_paired_n": 2}],
    })
    [converted] = convert_v2_policy(legacy, *runs).policy.metrics
    assert (converted.metric, converted.target, converted.k) == ("recall", "final_retrieval", 10)


def test_unreadable_step_limits_the_evidence_and_names_the_fix() -> None:
    manifest = {
        "dataset": {"query_hash": "q", "corpus_hash": "c", "qrel_hash": "r"}, "labeling": {"method": "gold"},
        "counts": {"attempted": 2, "completed": 2}, "unreadable_operators": ["screen_candidates"],
    }
    report = build_run_report(run_id="r", experiment_name="e", db_path="db", metrics={}, diagnostics=[], manifest=manifest)
    assert report.evidence_health == "limited"
    assert report.evidence_reasons == [
        "The output of screen_candidates could not be read as candidates, so that step is not scored: add a "
        "CaptureSpec in retobs_adapter.py whose `outputs` reads the candidate list from the returned object."
    ]
    clean = build_run_report(
        run_id="r", experiment_name="e", db_path="db", metrics={}, diagnostics=[], manifest={**manifest, "unreadable_operators": []},
    )
    assert clean.evidence_health == "ready"
