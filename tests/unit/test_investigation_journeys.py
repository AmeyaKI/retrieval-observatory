"""Journey projection checked against the golden fixture's hand-authored table."""

from __future__ import annotations

import inspect
import json

import pytest

from retrieval_observatory.datasets.judgments import ChunkMap, EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence.investigation import JourneyRow
from retrieval_observatory.evidence.journeys import project_trace_journeys, summarize_journeys, summarize_stages
from retrieval_observatory.tracing import candidate_journeys
from tests.fixtures.investigation_cases import (
    EVALUATION_SPEC,
    EXPECTED_CHUNK_JOURNEYS,
    EXPECTED_DOCUMENT_OUTCOMES,
    EXPECTED_STAGE_COUNTS,
    ExpectedDocumentOutcome,
    chunk_map,
    judgment_records,
    run_fixture,
)

EVENT_FIELDS = ("op_id", "kind", "branch", "reason", "reason_evidence", "boundary_complete", "input_rank", "output_rank")


@pytest.fixture(scope="module")
def run():
    return run_fixture()


@pytest.fixture(scope="module")
def judgments():
    return JudgmentSet.from_records(judgment_records())


@pytest.fixture(scope="module")
def chunks():
    return ChunkMap.from_pairs(chunk_map())


def _project(run, judgments, chunks, unit="document"):
    spec = EvaluationSpec.from_dict({**EVALUATION_SPEC, "unit": unit})
    return [row for trace in run.traces for row in project_trace_journeys(trace, judgments, spec, chunk_map=chunks)]


@pytest.fixture(scope="module")
def rows(run, judgments, chunks):
    return _project(run, judgments, chunks)


def _row(rows, query_id, namespace, entity_id):
    return next(r for r in rows if (r.query_id, r.namespace, r.entity_id) == (query_id, namespace, entity_id))


def _expected_outcome(expected: ExpectedDocumentOutcome) -> str:
    if expected.judgment == "relevant":
        if expected.final_membership == "included":
            return "relevant_delivered"
        if expected.in_final_output:
            return "retained_below_cutoff"
        if expected.loss_boundary == "not_observed":
            return "not_observed" if expected.capture_state == "complete" else "insufficient_evidence"
        return "insufficient_evidence" if expected.loss_boundary == "unknown" else "relevant_excluded"
    return "judged_nonrelevant" if expected.judgment == "nonrelevant" else "unjudged"


def test_every_expected_chunk_event_matches(rows):
    for journey in EXPECTED_CHUNK_JOURNEYS:
        row = next(
            r for r in rows if r.query_id == journey.query_id and r.namespace == journey.namespace and journey.chunk_id in r.occurrence_entity_ids
        )
        assert row.entity_id == journey.document_id
        actual = [e for e in row.events if e.occurrence_entity_id == journey.chunk_id]
        got = [tuple(getattr(e, f) for f in EVENT_FIELDS) for e in actual]
        want = [tuple(getattr(e, f) for f in EVENT_FIELDS) for e in journey.events]
        assert got == want, (journey.query_id, journey.chunk_id)
        assert all(e.operator_id == x.operator for e, x in zip(actual, journey.events))


def test_every_expected_document_outcome_matches(rows):
    fields = ("judgment", "grade", "final_membership", "in_final_output", "final_rank", "confusion", "capture_state", "loss_boundary")
    for expected in EXPECTED_DOCUMENT_OUTCOMES:
        row = _row(rows, expected.query_id, expected.namespace, expected.document_id)
        got = {f: getattr(row, f) for f in fields}
        assert got == {f: getattr(expected, f) for f in fields}, (expected.query_id, expected.document_id)
        assert row.outcome == _expected_outcome(expected), (expected.query_id, expected.document_id)


def test_no_rows_for_unobserved_unjudged_entities_and_never_observed_relevant_rows_exist(rows):
    # Every observed document (chunk table) plus every judged-relevant one (outcome table), nothing else.
    expected_keys = {(e.query_id, e.namespace, e.document_id) for e in EXPECTED_DOCUMENT_OUTCOMES} | {
        (j.query_id, j.namespace, j.document_id) for j in EXPECTED_CHUNK_JOURNEYS
    }
    unjudged_unobserved = {("q-refund", "kb", "doc-archive"), ("q-outage", "kb", "doc-1"), ("q-invoice", "kb", "doc-news")}
    actual_keys = {(r.query_id, r.namespace, r.entity_id) for r in rows}
    assert actual_keys == expected_keys
    assert not actual_keys & unjudged_unobserved
    archive = _row(rows, "q-invoice", "kb", "doc-archive")
    assert archive.observed is False
    assert archive.events == ()
    assert archive.outcome == "not_observed"
    assert archive.confusion == "FN"
    assert archive.priority == 0


def test_stage_summary_matches_hand_counts(run):
    summary = summarize_stages(run.traces)
    assert summary["by_op_id"] == EXPECTED_STAGE_COUNTS
    rerank = summary["by_operator_id"]["rerank"]
    assert rerank["queries_served"] == 6
    assert rerank["candidates_received"] == EXPECTED_STAGE_COUNTS["rerank@dense"]["candidates_received"] + EXPECTED_STAGE_COUNTS["rerank@lexical"]["candidates_received"]
    assert rerank["partial_boundaries"] == 1


def test_pairs_are_counted_once_not_per_occurrence(rows):
    faq_rows = [r for r in rows if (r.query_id, r.entity_id) == ("q-refund", "doc-faq")]
    assert len(faq_rows) == 1
    fuse = next(e for e in faq_rows[0].events if e.op_id == "fuse")
    assert (fuse.kind, fuse.reason, fuse.input_occurrences) == ("retained", "deduplicated", 2)
    summary = summarize_journeys(rows)
    assert summary["pairs"] == len(rows) == len(EXPECTED_DOCUMENT_OUTCOMES) + 1  # + q-refund doc-news (observed, unjudged)
    assert summary["by_query"]["q-refund"]["pairs"] == 5
    assert summary["by_entity"]["kb:doc-faq"] == {"queries": 2, "delivered": 1, "excluded": 0, "not_observed": 0, "unknown": 0}
    assert summary["relevant_final_misses_never_observed"] == 1
    assert summary["relevant_final_misses_observed_upstream"] == 0
    assert summary["by_confusion"] == {"TP": 5, "FP": 2, "TN": 1, "FN": 1, "unknown": 3}
    assert summary["by_loss_boundary"] == {"select": 1, "recency_filter": 1, "not_observed": 1}


def test_recovery_is_one_pair_with_removed_and_recovered_events(run, judgments, chunks):
    chunk_rows = _project(run, judgments, chunks, unit="chunk")
    guide2 = [r for r in chunk_rows if (r.query_id, r.entity_id) == ("q-invoice", "doc-guide/chunk-2")]
    assert len(guide2) == 1
    kinds = [(e.op_id, e.kind) for e in guide2[0].events]
    assert ("recency_filter", "removed") in kinds and ("expand", "recovered") in kinds
    recovered = next(e for e in guide2[0].events if e.kind == "recovered")
    assert recovered.source_occurrences == ("kb:doc-guide/chunk-1",)
    assert summarize_stages(run.traces)["by_op_id"]["expand"]["introduced"] == 1


def test_unknown_boundary_never_asserts_a_removal(rows):
    faq = _row(rows, "q-outage", "kb", "doc-faq")
    event = next(e for e in faq.events if e.op_id == "rerank@lexical")
    assert (event.kind, event.reason, event.reason_evidence, event.boundary_complete) == ("unknown", None, "unavailable", False)
    assert faq.capture_state == "partial"
    assert faq.final_membership == "included" and faq.outcome == "judged_nonrelevant"
    assert not any(e.kind == "removed" for e in faq.events)


def test_chunk_unit_projection_does_not_inherit_document_grades(run, judgments, chunks):
    chunk_rows = _project(run, judgments, chunks, unit="chunk")
    guide2 = _row(chunk_rows, "q-invoice", "kb", "doc-guide/chunk-2")
    assert (guide2.judgment, guide2.grade, guide2.final_membership) == ("relevant", 1, "excluded")
    assert guide2.loss_boundary == "select"
    assert guide2.outcome == "relevant_excluded" and guide2.confusion == "FN"
    guide1 = _row(chunk_rows, "q-invoice", "kb", "doc-guide/chunk-1")
    assert (guide1.judgment, guide1.grade, guide1.outcome, guide1.confusion) == ("unjudged", None, "unjudged", "unknown")
    assert all(r.unit == "chunk" and r.occurrence_entity_ids == (r.entity_id,) for r in chunk_rows)


def test_rows_are_deterministic_and_serialisable(run, judgments, chunks, rows):
    again = _project(run, judgments, chunks)
    assert again == rows
    for row in rows:
        payload = json.loads(json.dumps(row.to_dict()))
        assert JourneyRow.from_dict(payload) == row
        assert row.investigation_link == (
            f"#/investigate?run=golden-run&pipeline=golden-hybrid&view=queries&query={row.query_id}"
            f"&trace={row.trace_id}&entity={row.namespace}%3A{row.entity_id}"
        )
    assert len({r.trace_digest for r in rows}) == 3
    assert len({r.judgment_digest for r in rows}) == 1 and len({r.evaluation_digest for r in rows}) == 1


def test_projection_ignores_filters_and_view_parameters(run, judgments, chunks):
    spec = EvaluationSpec.from_dict(EVALUATION_SPEC)
    for trace in reversed(run.traces):
        first = project_trace_journeys(trace, judgments, spec, chunk_map=chunks)
        second = project_trace_journeys(trace, judgments, spec, chunk_map=chunks)
        assert first == second
        assert trace.to_dict() == trace.to_dict()


async def test_compat_adapter_matches_fixture_survival(run):
    trace = next(t for t in run.traces if t.query_id == "q-refund")
    qrels = {"doc-policy": 2, "doc-faq": 1, "doc-legal": 0}
    rows = await candidate_journeys.build_candidate_journeys([trace], query_id="q-refund", query_text="how do I get a refund", qrels_for_query=qrels, k=3)
    by_doc = {row["doc_id"]: row for row in rows}
    assert {doc: (row["survived"], row["final_rank"]) for doc, row in by_doc.items()} == {
        "doc-faq": (True, 1),
        "doc-policy": (True, 2),
        "doc-guide": (True, 3),
        "doc-legal": (True, 4),
        "doc-news": (False, None),
    }
    assert by_doc["doc-policy"]["outcome"] == "relevant_retained" and by_doc["doc-policy"]["relevant"] is True
    assert by_doc["doc-news"]["dropped_at"] == "recency_filter"
    assert by_doc["doc-news"]["drop_reason"] == "stale_year" and by_doc["doc-news"]["drop_reason_inferred"] is False
    assert all(row["miss_type"] is None for row in rows)
    assert "replay" not in inspect.getsource(candidate_journeys)
