"""Journey-based comparison: the diff rules on the golden fixture, then the compare route end to end.

The candidate run is the golden run with q-refund's recorded selection changed by hand (``candidate_traces``):
doc-guide leaves the top 3 (lost), doc-legal enters it (gained), faq/policy swap ranks (rank_changed) and
doc-news' removal moves from ``recency_filter`` to ``rerank@lexical`` (path_changed). Every other row is unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from retrieval_observatory.datasets.judgments import ChunkMap, EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence.investigation import JourneyRow
from retrieval_observatory.evidence.journeys import project_trace_journeys
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.lineage_diff import align_stages, diff_journeys, summarize_journey_diff
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace
from tests.fixtures.investigation_cases import run_fixture
from tests.unit.test_investigation_api import PIPELINE, RUN, _build, _client, _get

CANDIDATE = "cand-run"
SPEC = EvaluationSpec(k=3)
ALIGNED = {"q-refund": "aligned", "q-outage": "aligned", "q-invoice": "aligned"}
Key = tuple[str, str, str]


def _span(trace: RetrievalTrace, op_id: str) -> OperatorSpan:
    return next(span for span in trace.spans if span.op_id == op_id)


def _with_span(trace: RetrievalTrace, op_id: str, **changes) -> RetrievalTrace:
    return replace(trace, spans=tuple(replace(span, **changes) if span.op_id == op_id else span for span in trace.spans))


def _ranked(candidates: tuple[Candidate, ...], order: list[str]) -> tuple[Candidate, ...]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    return tuple(replace(by_id[candidate_id], rank=rank, output_rank=rank) for rank, candidate_id in enumerate(order, start=1))


def candidate_traces() -> list[RetrievalTrace]:
    traces = []
    for trace in run_fixture().traces:
        if trace.query_id == "q-refund":
            select = _span(trace, "select")
            trace = _with_span(trace, "select", outputs=_ranked(select.outputs, ["kb:doc-policy/chunk-1", "kb:doc-faq/chunk-1", "kb:doc-legal/chunk-1"]))
            recency = _span(trace, "recency_filter")
            news = next(c for c in recency.input_groups["lexical"] if c.candidate_id == "kb:doc-news/chunk-1")
            kept = (*recency.outputs, replace(news, rank=4, input_rank=None, output_rank=4, drop_reason=None, decision_reason=None))
            trace = _with_span(trace, "recency_filter", outputs=kept)
            trace = _with_span(trace, "rerank@lexical", input_groups={"recency_filter": kept})
        traces.append(replace(trace, run_id=CANDIDATE, trace_id=f"cand-{trace.trace_id}"))
    return traces


def _rows(traces) -> list[JourneyRow]:
    fixture = run_fixture()
    judgments = JudgmentSet.from_records(fixture.judgments)
    chunk_map = ChunkMap.from_pairs(fixture.chunk_map)
    return [row for trace in traces for row in project_trace_journeys(trace, judgments, SPEC, chunk_map=chunk_map)]


@pytest.fixture(scope="module")
def sides() -> tuple[list[JourneyRow], list[JourneyRow]]:
    return _rows(run_fixture().traces), _rows(candidate_traces())


def _by_key(rows) -> dict[Key, object]:
    return {(row.query_id, row.namespace, row.entity_id): row for row in rows}


def _stage_dicts(trace: RetrievalTrace) -> list[dict]:
    return [{"op_id": span.op_id, "operator_id": span.operator_id or span.op_id} for span in trace.spans]


# ---------------------------------------------------------------------------
# diff_journeys
# ---------------------------------------------------------------------------


def test_every_change_kind_and_ordering_from_the_golden_fixture(sides) -> None:
    baseline, candidate = sides
    rows = diff_journeys(baseline, candidate, query_alignment=ALIGNED)
    assert [row.change for row in rows[:5]] == ["lost", "gained", "rank_changed", "rank_changed", "path_changed"]
    assert [row.priority for row in rows] == sorted(row.priority for row in rows)
    assert all(row.change == "unchanged" for row in rows[5:]) and all(row.alignment == "aligned" for row in rows)
    by_key = _by_key(rows)
    guide = by_key[("q-refund", "kb", "doc-guide")]
    assert (guide.change, guide.detail) == ("lost", "included at rank 3 → excluded (select)")
    assert guide.baseline.final_rank == 3 and guide.candidate.final_membership == "excluded" and guide.candidate.loss_boundary == "select"
    assert guide.candidate.events_summary[-1] == "select:removed" and guide.baseline.events_summary[-1] == "select:promoted"
    assert guide.candidate.investigation_link.startswith("#/investigate?run=cand-run&")
    legal = by_key[("q-refund", "kb", "doc-legal")]
    assert (legal.change, legal.detail) == ("gained", "excluded at rank 4 (select) → included at rank 3")
    assert by_key[("q-refund", "kb", "doc-faq")].detail == "included at rank 1 → included at rank 2"
    assert by_key[("q-refund", "kb", "doc-policy")].detail == "included at rank 2 → included at rank 1"
    news = by_key[("q-refund", "kb", "doc-news")]
    assert (news.change, news.detail) == ("path_changed", "excluded (recency_filter) → excluded (rerank@lexical)")
    assert news.candidate.events_summary == ("lexical:introduced", "recency_filter:demoted", "rerank@lexical:removed")
    assert {key for key, row in by_key.items() if row.capture_limited} == {("q-outage", "kb", "doc-faq"), ("q-outage", "kb", "doc-guide")}
    archive = by_key[("q-invoice", "kb", "doc-archive")]
    assert archive.change == "unchanged" and archive.baseline.outcome == "not_observed" and archive.unit == "document"
    assert all("cause" not in row.detail for row in rows)


def test_unknown_membership_is_limited_evidence_not_a_loss(sides) -> None:
    baseline, _ = sides
    faq = next(row for row in baseline if (row.query_id, row.entity_id) == ("q-refund", "doc-faq"))
    unknown = replace(faq, final_membership="unknown", in_final_output=None, final_rank=None, outcome="insufficient_evidence")
    (one_side,) = diff_journeys([faq], [unknown], query_alignment=ALIGNED)
    assert (one_side.change, one_side.capture_limited) == ("membership_changed", True)
    assert one_side.detail == "included at rank 1 → membership unknown (final boundary not fully captured)"
    (both,) = diff_journeys([unknown], [unknown], query_alignment=ALIGNED)
    assert (both.change, both.capture_limited) == ("unchanged", True)


def test_query_unaligned_rows_keep_both_sides_without_a_change(sides) -> None:
    baseline, candidate = sides
    rows = diff_journeys(baseline, candidate, query_alignment={"q-refund": "query_unaligned"})
    refund = [row for row in rows if row.query_id == "q-refund"]
    assert refund and all((row.alignment, row.change, row.priority) == ("query_unaligned", "unaligned", 5) for row in refund)
    assert all(row.baseline is not None and row.candidate is not None for row in refund)
    assert all(row.alignment == "aligned" for row in rows if row.query_id != "q-refund")  # absent from the mapping: aligned


def test_entity_revision_change_compares_document_membership_only(sides) -> None:
    baseline, candidate = sides
    rows = diff_journeys(
        [replace(row, entity_revision="rev-1") for row in baseline if row.query_id == "q-refund"],
        [replace(row, entity_revision="rev-2") for row in candidate if row.query_id == "q-refund"],
        query_alignment=ALIGNED,
    )
    by_key = _by_key(rows)
    assert {row.alignment for row in rows} == {"entity_revision_changed"}
    assert by_key[("q-refund", "kb", "doc-guide")].change == "lost" and by_key[("q-refund", "kb", "doc-legal")].change == "gained"
    faq = by_key[("q-refund", "kb", "doc-faq")]
    assert faq.change == "unchanged" and faq.detail.startswith("entity revision changed (rev-1 → rev-2); ") and faq.detail.endswith("exact chunk diff unavailable")


def test_corpus_change_marks_every_row_unaligned_with_sides_filled(sides) -> None:
    baseline, candidate = sides
    rows = diff_journeys(baseline, candidate, query_alignment=ALIGNED, corpus_changed=True)
    assert rows and {(row.alignment, row.change) for row in rows} == {("corpus_changed", "unaligned")}
    assert all(row.baseline is not None and row.candidate is not None for row in rows)


def test_entity_or_query_missing_on_one_side(sides) -> None:
    baseline, candidate = sides
    added = replace(next(row for row in candidate if (row.query_id, row.entity_id) == ("q-invoice", "doc-guide")), entity_id="doc-new")
    rows = diff_journeys(baseline, [*(row for row in candidate if (row.query_id, row.entity_id) != ("q-invoice", "doc-1")), added], query_alignment=ALIGNED)
    by_key = _by_key(rows)
    gone = by_key[("q-invoice", "kb", "doc-1")]
    assert (gone.alignment, gone.change, gone.candidate) == ("missing_in_candidate", "lost", None)
    assert gone.detail == "included at rank 3 → excluded (not_observed); entity has no row in the candidate run"
    new = by_key[("q-invoice", "kb", "doc-new")]
    assert (new.alignment, new.change, new.baseline) == ("missing_in_baseline", "gained", None)
    only_baseline = diff_journeys(baseline, [row for row in candidate if row.query_id != "q-outage"], query_alignment=ALIGNED)
    outage = [row for row in only_baseline if row.query_id == "q-outage"]
    assert outage and {(row.alignment, row.change) for row in outage} == {("missing_in_candidate", "unaligned")}


def test_align_stages_matches_by_operator_id_and_lists_added_stages() -> None:
    trace = run_fixture().traces[0]
    baseline = _stage_dicts(trace)
    renamed = [{**stage, "op_id": "rerank@fast"} if stage["op_id"] == "rerank@dense" else stage for stage in baseline]
    alignment = align_stages(baseline, [*renamed, {"op_id": "boost", "operator_id": "boost"}])
    assert ("rerank@dense", "rerank@fast") in alignment.matched and ("rerank@lexical", "rerank@lexical") in alignment.matched
    assert alignment.candidate_only == ("boost",) and alignment.baseline_only == ()
    dropped = align_stages(baseline, [stage for stage in baseline if stage["op_id"] != "expand"])
    assert dropped.baseline_only == ("expand",) and dropped.candidate_only == ()
    assert dropped.to_dict()["matched"][0] == ["dense", "dense"]


def test_summarize_journey_diff_counts_unique_pairs(sides) -> None:
    baseline, candidate = sides
    rows = diff_journeys(baseline, candidate, query_alignment=ALIGNED)
    summary = summarize_journey_diff([*rows, *rows])
    assert summary["pairs"] == len(rows) == 12
    assert summary["by_change"] == {"lost": 2, "gained": 2, "membership_changed": 0, "rank_changed": 4, "path_changed": 2, "unaligned": 0, "unchanged": 14}
    assert summary["by_alignment"] == {"aligned": 24} and summary["capture_limited"] == 4


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------


async def _seed_pair(db_path: Path, *, candidate_dataset: dict, outage_text: str | None = None) -> None:
    fixture = run_fixture()
    base = {"normalized_config": {"metrics": {"recall_at_k": [3]}}, "counts": {"attempted": 3}, "judgment_records": fixture.judgments, "chunk_map": fixture.chunk_map}
    store = SQLiteStore(str(db_path))
    await store.init_db()
    for run_id, traces, dataset in ((RUN, fixture.traces, {"corpus_hash": "corpus-1", "query_input_hash": "queries-1"}), (CANDIDATE, candidate_traces(), candidate_dataset)):
        await store.save_run(run_id, "golden", json.dumps({}))
        await store.save_run_manifest(run_id, {**base, "dataset": dataset})
        await store.save_traces(traces)
        queries = fixture.queries
        if run_id == CANDIDATE and outage_text is not None:
            queries = [replace(query, text=outage_text) if query.query_id == "q-outage" else query for query in queries]
        await store.save_run_queries(run_id, queries, "golden")


@pytest.fixture
def pair_db(tmp_path: Path) -> Path:
    path = tmp_path / "pair.db"
    asyncio.run(_seed_pair(path, candidate_dataset={"corpus_hash": "corpus-1", "query_input_hash": "queries-1"}))
    return path


def _codes(envelope: dict) -> set[str]:
    return {finding["code"] for finding in envelope["findings"]}


def test_compare_route_orders_lost_first_and_reports_compatibility(pair_db: Path) -> None:
    client, base = _client(pair_db)
    _build(client, base, RUN)
    _build(client, base, CANDIDATE)
    envelope = _get(client, base, f"{CANDIDATE}/compare", against=RUN)
    rows = envelope["rows"]
    assert (rows[0]["change"], rows[0]["query_id"], rows[0]["entity_id"]) == ("lost", "q-refund", "doc-guide")
    assert [row["change"] for row in rows[:5]] == ["lost", "gained", "rank_changed", "rank_changed", "path_changed"]
    assert envelope["total"] == 12 and envelope["next_cursor"] is None and envelope["stages"] is None
    assert envelope["capabilities"]["projection"] == "ready" and envelope["capabilities"]["capture"] == {"complete_rows": 10, "partial_rows": 2}
    assert rows[0]["baseline"]["trace_id"] == "trace-q-refund" and rows[0]["candidate"]["trace_id"] == "cand-trace-q-refund"
    assert rows[0]["candidate"]["events_summary"][-1] == "select:removed"
    comparison = envelope["comparison"]
    assert (comparison["baseline_run_id"], comparison["candidate_run_id"], comparison["stage_alignment"]) == (RUN, CANDIDATE, None)
    assert comparison["compatibility"]["corpus_changed"] is False and comparison["compatibility"]["query_inputs_identical"] is True
    assert set(comparison["compatibility"]["provenance"]) == {"invariants", "interventions", "consistency", "unknown_fields"}
    assert all(finding["code"] != "corpus_identity_mismatch" for finding in comparison["compatibility"]["findings"])
    assert comparison["summary"]["by_change"]["lost"] == 1 and comparison["summary"] == envelope["summary"]
    assert {"unsupported_corpus_change", "comparison_partial", "projection_unavailable"}.isdisjoint(_codes(envelope))
    assert envelope["scope"]["run_id"] == CANDIDATE and "query_id" not in envelope["scope"]

    walked, cursor = [], None
    while True:
        page = _get(client, base, f"{CANDIDATE}/compare", against=RUN, limit=5, **({"cursor": cursor} if cursor else {}))
        walked.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [(r["query_id"], r["entity_id"]) for r in walked] == [(r["query_id"], r["entity_id"]) for r in rows]


def test_compare_single_query_aligns_stages_and_projects_on_the_fly(pair_db: Path) -> None:
    client, base = _client(pair_db)
    unindexed = _get(client, base, f"{CANDIDATE}/compare", against=RUN)
    assert unindexed["rows"] == [] and unindexed["capabilities"]["projection"] == "unavailable"
    assert {f["detail"] for f in unindexed["findings"] if f["code"] == "projection_unavailable"} == {
        f"no complete projection for run '{RUN}' pipeline '{PIPELINE}'",
        f"no complete projection for run '{CANDIDATE}' pipeline '{PIPELINE}'",
    }
    for _ in range(2):  # first on the fly, then from both projections
        envelope = _get(client, base, f"{CANDIDATE}/compare/q-refund", against=RUN)
        assert {row["query_id"] for row in envelope["rows"]} == {"q-refund"} and envelope["scope"]["query_id"] == "q-refund"
        assert [row["change"] for row in envelope["rows"][:5]] == ["lost", "gained", "rank_changed", "rank_changed", "path_changed"]
        alignment = envelope["comparison"]["stage_alignment"]
        assert ["rerank@dense", "rerank@dense"] in alignment["matched"] and alignment["baseline_only"] == [] and alignment["candidate_only"] == []
        _build(client, base, RUN)
        _build(client, base, CANDIDATE)
    assert _get(client, base, f"{CANDIDATE}/compare", against=RUN, query="q-outage")["rows"][0]["query_id"] == "q-outage"
    missing = client.get(f"{base}/{CANDIDATE}/compare/q-missing", params={"pipeline_id": PIPELINE, "against": RUN})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "query_not_found"


def test_compare_with_changed_corpus_blocks_matching(tmp_path: Path) -> None:
    db_path = tmp_path / "corpus.db"
    asyncio.run(_seed_pair(db_path, candidate_dataset={"corpus_hash": "corpus-2", "query_input_hash": "queries-1"}))
    client, base = _client(db_path)
    _build(client, base, RUN)
    _build(client, base, CANDIDATE)
    envelope = _get(client, base, f"{CANDIDATE}/compare", against=RUN)
    assert envelope["comparison"]["compatibility"]["corpus_changed"] is True
    assert "corpus_identity_mismatch" in {f["code"] for f in envelope["comparison"]["compatibility"]["findings"]}
    blocked = next(f for f in envelope["findings"] if f["code"] == "unsupported_corpus_change")
    assert blocked["action"] == "compare final outputs per run; matched release claims are blocked"
    assert envelope["rows"] and {(r["alignment"], r["change"]) for r in envelope["rows"]} == {("corpus_changed", "unaligned")}
    assert all(r["baseline"] is not None and r["candidate"] is not None for r in envelope["rows"])


def test_compare_with_changed_query_text_marks_the_query_unaligned(tmp_path: Path) -> None:
    db_path = tmp_path / "queries.db"
    asyncio.run(_seed_pair(db_path, candidate_dataset={"corpus_hash": "corpus-1", "query_input_hash": "queries-2"}, outage_text="why is the site down today"))
    client, base = _client(db_path)
    _build(client, base, RUN)
    _build(client, base, CANDIDATE)
    envelope = _get(client, base, f"{CANDIDATE}/compare", against=RUN)
    assert envelope["comparison"]["compatibility"]["query_inputs_identical"] is False and "comparison_partial" in _codes(envelope)
    outage = [row for row in envelope["rows"] if row["query_id"] == "q-outage"]
    assert outage and {(r["alignment"], r["change"]) for r in outage} == {("query_unaligned", "unaligned")}
    assert envelope["rows"][0]["change"] == "lost" and envelope["comparison"]["summary"]["by_alignment"] == {"aligned": 9, "query_unaligned": 3}


def test_compare_requires_against_and_a_valid_cursor(pair_db: Path) -> None:
    client, base = _client(pair_db)
    response = client.get(f"{base}/{CANDIDATE}/compare", params={"pipeline_id": PIPELINE})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "comparison_run_required"
    response = client.get(f"{base}/{CANDIDATE}/compare", params={"pipeline_id": PIPELINE, "against": RUN, "cursor": "nope"})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "invalid_cursor"
    response = client.get(f"{base}/{CANDIDATE}/compare", params={"pipeline_id": PIPELINE, "against": "no-run"})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "run_not_found"


def test_compare_gets_are_read_only(pair_db: Path) -> None:
    writable, base = _client(pair_db)
    _build(writable, base, RUN)
    before = hashlib.sha256(pair_db.read_bytes()).hexdigest()  # only the baseline is indexed: the candidate projects on the fly
    client, base = _client(pair_db, read_only=True)
    for path in (f"{CANDIDATE}/compare", f"{CANDIDATE}/compare/q-refund"):
        assert client.get(f"{base}/{path}", params={"pipeline_id": PIPELINE, "against": RUN}).status_code == 200, path
        assert hashlib.sha256(pair_db.read_bytes()).hexdigest() == before, path
