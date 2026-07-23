import pytest

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.lineage_contract import LineageEvidence
from retrieval_observatory.tracing.model import Candidate, OperatorSpan


def test_fusion_output_retains_multiple_candidate_parents():
    fused = Candidate(
        candidate_id="fused:42",
        logical_chunk_id="chunk:42",
        parent_candidate_ids=("lex:42", "vec:42"),
        doc_id="chunk:42",
        score=0.9,
        rank=1,
    )

    assert fused.parent_candidate_ids == ("lex:42", "vec:42")
    assert fused.identity_evidence == "recorded"


def test_legacy_doc_only_candidate_is_marked_legacy_inferred():
    candidate = Candidate.from_dict({"doc_id": "d1", "score": 1.0, "rank": 1})

    assert candidate.candidate_id == "d1"
    assert candidate.logical_chunk_id == "d1"
    assert candidate.identity_evidence == "legacy_inferred"


def test_legacy_drop_reason_is_not_upgraded_to_recorded_decision_evidence():
    candidate = Candidate.from_dict(
        {"doc_id": "d1", "score": 1.0, "rank": 1, "drop_reason": "filtered"}
    )

    assert candidate.drop_reason == "filtered"
    assert candidate.decision_reason is None
    assert candidate.decision_evidence == "legacy_inferred"


def test_operator_span_rejects_duplicate_candidate_ids_per_set():
    duplicates = (
        Candidate("d1", 1.0, 1, candidate_id="candidate:1"),
        Candidate("d2", 0.5, 2, candidate_id="candidate:1"),
    )

    with pytest.raises(ValueError, match="candidate IDs must be unique"):
        OperatorSpan.source("source", "source", duplicates)


def test_recorded_derived_candidate_requires_declared_parent():
    with pytest.raises(ValueError, match="recorded derived candidate"):
        Candidate(
            "chunk:42",
            0.9,
            1,
            candidate_id="fused:42",
            logical_chunk_id="chunk:42",
            decision_reason="fused",
            decision_evidence="recorded",
        )


def test_transition_matches_candidate_id_before_document_id():
    lexical = Candidate("chunk:42", 0.7, 1, candidate_id="lex:42", logical_chunk_id="chunk:42")
    vector = Candidate("chunk:42", 0.8, 1, candidate_id="vec:42", logical_chunk_id="chunk:42")

    transition = build_candidate_transition(
        input_groups={"lex": (lexical,), "vec": (vector,)},
        output_items=[{"doc_id": "chunk:42", "candidate_id": "vec:42", "score": 0.9, "rank": 1}],
        op_id="rerank",
        op_type="RERANK",
    )

    assert transition.outputs[0].candidate_id == "vec:42"
    assert transition.outputs[0].parent_candidate_ids == ("vec:42",)
    assert transition.input_groups["lex"][0].output_rank is None
    assert transition.input_groups["vec"][0].output_rank == 1


def test_transition_falls_back_to_document_id_for_unmatched_legacy_output_identity():
    source = Candidate("d1", 0.8, 1, candidate_id="source:d1")

    transition = build_candidate_transition(
        input_groups={"source": (source,)},
        output_items=[Candidate("d1", 0.9, 1)],
        op_id="rerank",
        op_type="RERANK",
    )

    assert transition.input_groups["source"][0].output_rank == 1
    assert transition.outputs[0].parent_candidate_ids == ("source:d1",)


def test_inferred_and_recorded_exit_reasons_have_distinct_evidence():
    candidate = Candidate("d1", 1.0, 1, candidate_id="candidate:1")

    inferred = build_candidate_transition(
        input_groups={"source": (candidate,)},
        output_items=[],
        op_id="filter",
        op_type="FILTER",
    ).input_groups["source"][0]
    recorded = build_candidate_transition(
        input_groups={"source": (candidate,)},
        output_items=[],
        op_id="filter",
        op_type="FILTER",
        decision_reasons={"candidate:1": "outside_time_window"},
    ).input_groups["source"][0]

    assert inferred.drop_reason == "filtered"
    assert inferred.decision_reason is None
    assert inferred.decision_evidence == "legacy_inferred"
    assert recorded.decision_reason == "outside_time_window"
    assert recorded.decision_evidence == "recorded"


def test_lineage_evidence_vocabulary_is_exact():
    values: tuple[LineageEvidence, ...] = ("recorded", "legacy_inferred", "partial", "unavailable")

    assert values == ("recorded", "legacy_inferred", "partial", "unavailable")
