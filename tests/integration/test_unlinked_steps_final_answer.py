"""Three decorated steps called in sequence with no declared parent links, evaluated through
``retobs evaluate``: the step whose return value is not a candidate list is recorded as
unreadable (never as invented ids "1".."4"), the trace has one final step (the one whose output
the callable returned), and the run summary, the per-question evidence and verify agree."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

import retrieval_observatory as ro
from retrieval_observatory.cli import app
from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping
from retrieval_observatory.integrations.verify import verify_observed_traces
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore

PIPELINE = '''
from types import SimpleNamespace

from retrieval_observatory.sdk.observe import observe, trace_scope

LANES = {
    "alpha": (["doc-a1", "doc-x9", "doc-b2"], ["doc-c3", "doc-b2"]),
    "beta": (["doc-d4", "doc-a1"], ["doc-x9", "doc-e5"]),
}


def _items(*ids):
    return [SimpleNamespace(id=doc_id, score=float(len(ids) - rank)) for rank, doc_id in enumerate(ids)]


@observe("FUSE", op_id="merge_lanes")
def merge_lanes(a, b):
    return _items(*dict.fromkeys([*a, *b]))


@observe("FILTER", op_id="screen_candidates")
def screen_candidates(mode, rules, items):
    kept = [item for item in items if item.id not in rules["blocked"]]
    dropped = [item for item in items if item.id in rules["blocked"]]
    return kept, dropped, [], not kept


@observe("RERANK", op_id="diversify")
def diversify(items):
    return _items(*[item.id for item in reversed(items)])


@trace_scope("svc", "pipe", db_path=SCOPE_DB)
def retrieve(query):
    kept, _dropped, _errors, _empty = screen_candidates("strict", {"blocked": {"doc-x9"}}, merge_lanes(*LANES[query]))
    return diversify(kept)


def retrieve_merged(query):
    merged = merge_lanes(*LANES[query])
    kept, _dropped, _errors, _empty = screen_candidates("strict", {"blocked": {"doc-x9"}}, merged)
    diversify(kept)  # computed, then discarded: the caller ships the merged list
    return merged


def retrieve_trimmed(query):
    kept, _dropped, _errors, _empty = screen_candidates("strict", {"blocked": {"doc-x9"}}, merge_lanes(*LANES[query]))
    return [item for item in diversify(kept) if item.id != "doc-a1"]  # an untraced post-filter
'''
QUERIES = [{"query_id": "q1", "text": "alpha"}, {"query_id": "q2", "text": "beta"}]
QRELS = {"q1": {"doc-a1": 1, "doc-c3": 1, "doc-e5": 1}, "q2": {"doc-x9": 1, "doc-d4": 1}}
CORPUS = {doc_id: doc_id for doc_id in ("doc-a1", "doc-b2", "doc-c3", "doc-d4", "doc-e5", "doc-x9")}
# What ``retrieve`` returns: the blocked document screened out, the rest reversed by diversify.
RETURNED = {"q1": ["doc-c3", "doc-b2", "doc-a1"], "q2": ["doc-e5", "doc-a1", "doc-d4"]}
INVENTED = {"1", "2", "3", "4", "default:1", "default:2", "default:3", "default:4"}


def _write_inputs(tmp_path: Path) -> list[str]:
    (tmp_path / "pipeline.py").write_text(PIPELINE.replace("SCOPE_DB", repr(str(tmp_path / "scope.db"))), encoding="utf-8")
    (tmp_path / "queries.jsonl").write_text("".join(json.dumps(row) + "\n" for row in QUERIES), encoding="utf-8")
    (tmp_path / "corpus.jsonl").write_text(
        "".join(json.dumps({"doc_id": doc_id, "text": text}) + "\n" for doc_id, text in CORPUS.items()), encoding="utf-8"
    )
    (tmp_path / "qrels.jsonl").write_text(
        "".join(
            json.dumps({"query_id": query_id, "doc_id": doc_id, "relevance": grade}) + "\n"
            for query_id, judged in QRELS.items() for doc_id, grade in judged.items()
        ),
        encoding="utf-8",
    )
    return [
        "--queries", str(tmp_path / "queries.jsonl"), "--qrels", str(tmp_path / "qrels.jsonl"),
        "--corpus", str(tmp_path / "corpus.jsonl"), "--db", str(tmp_path / "results.db"),
    ]


async def _traces(db_path: Path, run_id: str):
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    return {trace.query_id: trace for trace in await store.list_traces(TraceQuery(run_id=run_id))}


def _recall(returned: list[str], relevant: set[str], k: int) -> float:
    return len(set(returned[:k]) & relevant) / len(relevant)


def _headline_recall(report: dict) -> tuple[str, dict]:
    [(key, value)] = [(key, value) for key, value in report["metrics"].items() if value["metric_name"] == "recall"]
    return key, value


def test_unlinked_steps_record_no_invented_ids_and_summarise_the_returned_list(tmp_path: Path) -> None:
    db_path = tmp_path / "results.db"
    args = _write_inputs(tmp_path)
    result = CliRunner().invoke(app, ["evaluate", f"{tmp_path / 'pipeline.py'}:retrieve", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    run_id = report["run_id"]
    traces = asyncio.run(_traces(db_path, run_id))
    assert set(traces) == {"q1", "q2"}

    for query_id, trace in traces.items():
        # No candidate anywhere carries an id invented from its position.
        ids = {c.doc_id for span in trace.spans for c in (*span.inputs, *span.outputs)}
        assert not ids & INVENTED
        # The 4-tuple step is unreadable, recorded honestly with its returned shape.
        screen = trace.span("screen_candidates")
        assert screen.output_capture == "unavailable" and screen.outputs == ()
        [failure] = [item for item in trace.capture_failures if item["op_id"] == "screen_candidates"]
        assert failure["phase"] == "outputs" and failure["code"] == "candidate_ids_missing"
        assert failure["detail"] == "returned tuple of 4 items; item 1 is a list, not a candidate"
        # One final step: the step whose output the callable returned; no return span was needed.
        assert trace.final_op_ids == ("diversify",)
        assert [span.op_id for span in trace.spans] == ["merge_lanes", "screen_candidates", "diversify"]
        assert [c.doc_id for c in trace.span("diversify").outputs] == RETURNED[query_id]

    # The run summary is recall at the final answer, computed by hand from the returned lists.
    expected = sum(_recall(RETURNED[q], {d for d, g in QRELS[q].items() if g > 0}, 10) for q in QRELS) / len(QRELS)
    key, recall = _headline_recall(report)
    assert key == "retrieve|stage0|recall@10|branch=diversify"
    assert abs(recall["mean"] - expected) < 1e-9 and recall["n"] == 2

    # `retobs report` shows the same summary.
    stored = CliRunner().invoke(app, ["report", run_id, "--db", str(db_path), "--format", "json"])
    assert stored.exit_code == 0, stored.output
    stored_key, stored_recall = _headline_recall(json.loads(stored.stdout))
    assert (stored_key, stored_recall["mean"], stored_recall["n"]) == (key, recall["mean"], recall["n"])

    # Per-step numbers stay available per step; the unreadable step has no quality rows at all.
    rows = asyncio.run(_metric_rows(db_path, run_id))
    assert {(row["branch_id"], row["metric_name"]) for row in rows if row["metric_name"] == "recall"} == {
        ("merge_lanes", "recall"), ("diversify", "recall")
    }
    assert {row["metric_name"] for row in rows if row["branch_id"] == "screen_candidates"} == {"latency_ms"}

    # The per-question evidence inspect-query reads agrees with the summary.
    for query_id, returned in RETURNED.items():
        evidence = ro.inspect_query(run_id, query_id, db_path=str(db_path))["investigation"]["rows"]
        assert not {row["entity_id"] for row in evidence} & INVENTED
        relevant = [row for row in evidence if row["judgment"] == "relevant"]
        delivered = {row["entity_id"]: row["final_rank"] for row in relevant if row["outcome"] == "relevant_delivered"}
        assert delivered == {doc_id: returned.index(doc_id) + 1 for doc_id in returned if QRELS[query_id].get(doc_id)}
        assert len(delivered) / len(relevant) == _recall(returned, set(QRELS[query_id]), 10)


async def _metric_rows(db_path: Path, run_id: str):
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    return [row for row in await store.get_metrics(run_id) if row["stage_index"] == 0]


def test_summary_is_the_returned_step_even_when_a_later_step_fired(tmp_path: Path) -> None:
    args = _write_inputs(tmp_path)
    result = CliRunner().invoke(app, ["evaluate", f"{tmp_path / 'pipeline.py'}:retrieve_merged", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    traces = asyncio.run(_traces(tmp_path / "results.db", report["run_id"]))
    merged = {query_id: [c.doc_id for c in trace.span("merge_lanes").outputs] for query_id, trace in traces.items()}
    assert merged == {"q1": ["doc-a1", "doc-x9", "doc-b2", "doc-c3"], "q2": ["doc-d4", "doc-a1", "doc-x9", "doc-e5"]}
    assert all(trace.final_op_ids == ("merge_lanes",) for trace in traces.values())

    expected = sum(_recall(merged[q], set(QRELS[q]), 10) for q in QRELS) / len(QRELS)
    key, recall = _headline_recall(report)
    assert key == "retrieve_merged|stage0|recall@10|branch=merge_lanes"
    assert abs(recall["mean"] - expected) < 1e-9


def test_summary_is_the_returned_list_when_no_step_emitted_it(tmp_path: Path) -> None:
    args = _write_inputs(tmp_path)
    result = CliRunner().invoke(app, ["evaluate", f"{tmp_path / 'pipeline.py'}:retrieve_trimmed", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    traces = asyncio.run(_traces(tmp_path / "results.db", report["run_id"]))
    returned = {"q1": ["doc-c3", "doc-b2"], "q2": ["doc-e5", "doc-d4"]}
    for query_id, trace in traces.items():
        assert trace.final_op_ids == ("return",)
        boundary = trace.span("return")
        assert boundary.parent_ids == ("merge_lanes", "screen_candidates", "diversify")
        assert [c.doc_id for c in boundary.outputs] == returned[query_id]

    expected = sum(_recall(returned[q], set(QRELS[q]), 10) for q in QRELS) / len(QRELS)
    key, recall = _headline_recall(report)
    assert key == "retrieve_trimmed|stage1|recall@10"
    assert abs(recall["mean"] - expected) < 1e-9 and recall["n"] == 2


def test_verify_reports_the_unreadable_step_with_its_op_id_and_fix(tmp_path: Path) -> None:
    db_path = tmp_path / "results.db"
    result = CliRunner().invoke(app, ["evaluate", f"{tmp_path / 'pipeline.py'}:retrieve", "--format", "json", *_write_inputs(tmp_path)])
    assert result.exit_code == 0, result.output
    traces = list(asyncio.run(_traces(db_path, json.loads(result.stdout)["run_id"])).values())
    operators = tuple(
        OperatorMapping(op_id, op_type, op_id, "pipeline.py")
        for op_id, op_type in (("merge_lanes", "FUSE"), ("screen_candidates", "FILTER"), ("diversify", "RERANK"))
    )
    manifest = IntegrationManifest(2, "plan", "evaluation", "retrieve", operators, {"doc_id": "id"}, ())

    verified = verify_observed_traces(manifest, traces)

    capture = verified.capabilities["actual_input_output_capture"]
    assert capture["status"] == "partial"
    [failure] = [item for item in capture["failures"] if item["code"] == "output_capture_unavailable"]
    assert failure["op_id"] == "screen_candidates"
    assert "candidate_ids_missing: returned tuple of 4 items; item 1 is a list, not a candidate" in failure["detail"]
    assert "CaptureSpec `screen_candidates_capture` in retobs_adapter.py" in failure["fix"]
    assert "reads the candidate list from the returned object" in failure["fix"]
    assert verified.capabilities["final_output_capture"]["status"] == "ready"
