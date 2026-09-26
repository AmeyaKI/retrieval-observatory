"""The golden investigation fixture is checked directly against raw spans; no journey code is imported."""

from __future__ import annotations

from collections import defaultdict

import pytest

from tests.fixtures.investigation_cases import (
    EVALUATION_SPEC,
    EXPECTED_CHUNK_JOURNEYS,
    EXPECTED_DOCUMENT_OUTCOMES,
    EXPECTED_STAGE_COUNTS,
    SCENARIO_COVERAGE,
    ExpectedChunkJourney,
    judgment_records,
    run_fixture,
)

OP_IDS = {"dense", "lexical", "recency_filter", "rerank@dense", "rerank@lexical", "fuse", "expand_gate", "expand", "select"}


@pytest.fixture(scope="module")
def fixture_run():
    return run_fixture()


def _trace(run, query_id):
    return next(trace for trace in run.traces if trace.query_id == query_id)


def _chunk_key(candidate) -> tuple[str, str]:
    return candidate.metadata["namespace"], candidate.logical_chunk_id


def _occurrences(span, key):
    return [(parent, c) for parent, candidates in span.input_groups.items() for c in candidates if _chunk_key(c) == key]


def _truncated(span) -> bool:
    return "capture" in span.params


def _dicts_without_timestamp(run):
    payloads = [trace.to_dict() for trace in run.traces]
    for payload in payloads:
        payload.pop("timestamp")
    return payloads


def test_fixture_is_deterministic():
    assert _dicts_without_timestamp(run_fixture()) == _dicts_without_timestamp(run_fixture())


def test_traces_validate_and_have_expected_topology(fixture_run):
    assert [query.query_id for query in fixture_run.queries] == [trace.query_id for trace in fixture_run.traces]
    for trace in fixture_run.traces:
        assert {span.op_id for span in trace.spans} == OP_IDS
        assert trace.final_op_ids == ("select",)
        expand = trace.span("expand")
        expand_on = trace.query_id == "q-invoice"
        assert expand.status == ("FIRED" if expand_on else "SKIPPED_BY_GATE")
        assert expand.gate_values == {"expand": expand_on}
        assert trace.span("expand_gate").gate_values == {"expand": expand_on}
        assert trace.span("select").parent_ids == (("expand",) if expand_on else ("expand_gate",))
        if not expand_on:
            assert expand.input_groups == {} and expand.outputs == ()
        for op_id in ("rerank@dense", "rerank@lexical"):
            span = trace.span(op_id)
            assert span.op_name == "rerank" and span.params["operator"] == "rerank"
    assert _trace(fixture_run, "q-outage").capture.candidates_truncated is True
    assert _trace(fixture_run, "q-outage").capture.lineage_evidence == "partial"
    assert _trace(fixture_run, "q-refund").capture.candidates_truncated is False


def test_recorded_inputs_are_actual_arguments(fixture_run):
    for trace in fixture_run.traces:
        calls = fixture_run.calls[trace.query_id]
        for span in trace.spans:
            if span.status != "FIRED" or not span.parent_ids:
                continue
            recorded = {parent: tuple(c.candidate_id for c in candidates) for parent, candidates in span.input_groups.items()}
            assert recorded == calls[span.op_id], (trace.query_id, span.op_id)
    outage = _trace(fixture_run, "q-outage")
    recorded_outputs = tuple(c.candidate_id for c in outage.span("rerank@lexical").outputs)
    next_input = tuple(c.candidate_id for c in outage.span("fuse").input_groups["rerank@lexical"])
    assert recorded_outputs == ("kb:doc-guide/chunk-1",)
    assert next_input == ("kb:doc-guide/chunk-1", "kb:doc-faq/chunk-1")
    assert outage.span("rerank@lexical").params["capture"] == {"outputs": "truncated", "recorded": 1, "returned": 2}


def _check_event(journey: ExpectedChunkJourney, event, span, earlier_events) -> None:
    key = (journey.namespace, journey.chunk_id)
    label = (journey.query_id, journey.chunk_id, event.op_id)
    occurrences = _occurrences(span, key)
    outputs = [c for c in span.outputs if _chunk_key(c) == key]
    assert len(outputs) <= 1, label
    assert event.operator == span.op_name, label
    assert event.branch == span.branch_id, label
    assert event.boundary_complete == (not _truncated(span)), label
    if event.kind in ("introduced", "recovered"):
        assert not occurrences and outputs, label
        assert outputs[0].rank == event.output_rank and event.input_rank is None, label
        assert outputs[0].add_reason == event.reason, label
        if event.kind == "recovered":
            assert any(earlier.kind == "removed" for earlier in earlier_events), label
        else:
            assert not any(earlier.kind == "removed" for earlier in earlier_events), label
        return
    assert occurrences, label
    if event.kind == "unknown":
        assert not outputs and _truncated(span), label
        assert event.reason is None and event.reason_evidence == "unavailable", label
        (_, candidate), = occurrences
        assert candidate.rank == event.input_rank, label
        assert candidate.decision_reason is None and candidate.drop_reason is None, label
        assert candidate.decision_evidence == "unavailable", label
        return
    if event.kind == "removed":
        assert not outputs and not _truncated(span), label
        (_, candidate), = occurrences
        assert candidate.rank == event.input_rank and event.output_rank is None, label
        assert event.reason_evidence == "recorded", label
        assert candidate.decision_reason == event.reason, label
        assert candidate.decision_evidence == "recorded", label
        return
    assert outputs and outputs[0].rank == event.output_rank, label
    if event.reason == "deduplicated":
        assert len(occurrences) >= 2 and event.kind == "retained", label
        assert event.input_rank == min(c.rank for _, c in occurrences), label
        assert outputs[0].metadata["fused_from"] == [parent for parent, _ in occurrences], label
        assert set(outputs[0].score_components) == {parent for parent, _ in occurrences}, label
        return
    assert event.reason is None, label
    (_, candidate), = occurrences
    assert candidate.rank == event.input_rank, label
    expected_kind = "retained" if event.input_rank == event.output_rank else "promoted" if event.output_rank < event.input_rank else "demoted"
    assert event.kind == expected_kind, label


def test_expected_chunk_events_match_raw_span_membership(fixture_run):
    seen_journeys = set()
    for journey in EXPECTED_CHUNK_JOURNEYS:
        trace = _trace(fixture_run, journey.query_id)
        key = (journey.namespace, journey.chunk_id)
        row = (journey.query_id, *key)
        assert row not in seen_journeys, row
        seen_journeys.add(row)
        assert [event.op_id for event in journey.events] == [
            span.op_id for span in trace.spans if _occurrences(span, key) or any(_chunk_key(c) == key for c in span.outputs)
        ], row
        for index, event in enumerate(journey.events):
            _check_event(journey, event, trace.span(event.op_id), journey.events[:index])
        final = [c for c in trace.span("select").outputs if _chunk_key(c) == key]
        assert journey.in_final_output == bool(final), row
        assert journey.final_rank == (final[0].rank if final else None), row
        if final:
            assert journey.document_id == final[0].document_id, row
    every_occurrence = {
        (trace.query_id, *_chunk_key(c))
        for trace in fixture_run.traces
        for span in trace.spans
        for c in (*span.inputs, *span.outputs)
    }
    assert seen_journeys == every_occurrence


def _document_grades(fixture_run) -> dict[tuple[str, str, str], int]:
    document_of = {(namespace, chunk_id): document_id for chunk_id, document_id, namespace in fixture_run.chunk_map}
    grades: dict[tuple[str, str, str], int] = {}
    for record in judgment_records():
        document_id = record["entity_id"] if record["unit"] == "document" else document_of[(record["namespace"], record["entity_id"])]
        key = (record["query_id"], record["namespace"], document_id)
        grades[key] = max(grades.get(key, 0), record["grade"])  # any_chunk aggregation
    return grades


def test_expected_document_outcomes_match_final_output_and_judgments(fixture_run):
    k, threshold = EVALUATION_SPEC["k"], EVALUATION_SPEC["relevance_threshold"]
    grades = _document_grades(fixture_run)
    final_ranks: dict[tuple[str, str, str], int] = {}
    for trace in fixture_run.traces:
        for candidate in trace.span("select").outputs:
            key = (trace.query_id, candidate.metadata["namespace"], candidate.document_id)
            final_ranks[key] = min(final_ranks.get(key, candidate.rank), candidate.rank)
    assert {(row.query_id, row.namespace, row.document_id) for row in EXPECTED_DOCUMENT_OUTCOMES} == set(grades) | set(final_ranks)
    for row in EXPECTED_DOCUMENT_OUTCOMES:
        key = (row.query_id, row.namespace, row.document_id)
        grade = grades.get(key)
        judgment = "unjudged" if grade is None else "relevant" if grade >= threshold else "nonrelevant"
        assert (row.judgment, row.grade) == (judgment, grade), key
        rank = final_ranks.get(key)
        assert (row.in_final_output, row.final_rank) == (rank is not None, rank), key
        included = rank is not None and rank <= k
        assert row.final_membership == ("included" if included else "excluded"), key
        confusion = "unknown" if judgment == "unjudged" else {(True, True): "TP", (True, False): "FN", (False, True): "FP", (False, False): "TN"}[(judgment == "relevant", included)]
        assert row.confusion == confusion, key
        assert (row.loss_boundary is None) == included, key
        trace = _trace(fixture_run, row.query_id)
        touches_truncated = any(
            _truncated(span) and any((c.metadata["namespace"], c.document_id) == key[1:] for c in (*span.inputs, *span.outputs))
            for span in trace.spans
        )
        assert row.capture_state == ("partial" if touches_truncated else "complete"), key
    archive_rows = [row for row in EXPECTED_DOCUMENT_OUTCOMES if row.document_id == "doc-archive"]
    assert archive_rows and all(row.confusion == "FN" and row.loss_boundary == "not_observed" for row in archive_rows)
    for trace in fixture_run.traces:
        for span in trace.spans:
            assert all(c.document_id != "doc-archive" for c in (*span.inputs, *span.outputs)), (trace.query_id, span.op_id)


def test_stage_counts_are_hand_countable(fixture_run):
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for trace in fixture_run.traces:
        for span in trace.spans:
            stage = counts[span.op_id]
            for field in ("queries_served", "queries_skipped", "candidates_received", "removal_events", "introduced", "partial_boundaries"):
                stage.setdefault(field, 0)
            if span.status == "SKIPPED_BY_GATE":
                stage["queries_skipped"] += 1
                continue
            stage["queries_served"] += 1
            stage["candidates_received"] += len(span.inputs)
            input_ids = {c.candidate_id for c in span.inputs}
            output_ids = {c.candidate_id for c in span.outputs}
            stage["introduced"] += sum(c.candidate_id not in input_ids for c in span.outputs)
            if _truncated(span):
                stage["partial_boundaries"] += 1
            else:
                stage["removal_events"] += sum(c.candidate_id not in output_ids for c in span.inputs)
    assert {op_id: dict(stage) for op_id, stage in counts.items()} == EXPECTED_STAGE_COUNTS


def test_scenario_coverage_keys_present_and_point_at_real_rows():
    expected_keys = {
        "branch_loss_with_survival", "repeated_invocation", "deduplication", "recovery", "unknown_capture", "explicit_nonrelevant_inclusion",
        "unjudged_inclusion", "never_retrieved", "namespace_collision", "retained_below_cutoff", "demotion",
        "query_scoped_relevance", "chunk_excluded_document_included",
    }
    assert set(SCENARIO_COVERAGE) == expected_keys
    chunk_rows = {(row.query_id, row.namespace, row.chunk_id) for row in EXPECTED_CHUNK_JOURNEYS}
    document_rows = {(row.query_id, row.namespace, row.document_id) for row in EXPECTED_DOCUMENT_OUTCOMES}
    for scenario, pointers in SCENARIO_COVERAGE.items():
        assert pointers, scenario
        for pointer in pointers:
            assert pointer in chunk_rows or pointer in document_rows, (scenario, pointer)
