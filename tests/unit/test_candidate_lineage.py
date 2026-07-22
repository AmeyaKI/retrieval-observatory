from __future__ import annotations

from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.model import (
    CaptureMetadata,
    Candidate,
    OperatorSpan,
    RetrievalTrace,
)


def _candidate(candidate_id: str, logical_chunk_id: str, rank: int = 1) -> Candidate:
    return Candidate(
        doc_id=logical_chunk_id,
        score=1.0 / rank,
        rank=rank,
        output_rank=rank,
        candidate_id=candidate_id,
        logical_chunk_id=logical_chunk_id,
    )


def _fusion_trace() -> RetrievalTrace:
    lexical = _candidate("lex:42", "chunk:42")
    vector = _candidate("vec:42", "chunk:42")
    fused = Candidate(
        doc_id="chunk:42",
        score=1.0,
        rank=1,
        output_rank=1,
        candidate_id="fused:42",
        logical_chunk_id="chunk:42",
        parent_candidate_ids=("lex:42", "vec:42"),
        decision_reason="fused",
        decision_evidence="recorded",
    )
    return RetrievalTrace(
        trace_id="trace-fusion",
        service_id="search",
        run_id="run-1",
        query_id="q1",
        query_text="private",
        pipeline_id="hybrid",
        spans=(
            OperatorSpan.source("lexical", "lexical", (lexical,)),
            OperatorSpan.source("vector", "vector", (vector,)),
            OperatorSpan(
                "fusion",
                "FUSE",
                "fusion",
                ("lexical", "vector"),
                "FIRED",
                1.0,
                input_groups={"lexical": (lexical,), "vector": (vector,)},
                outputs=(fused,),
            ),
        ),
        final_op_ids=("fusion",),
    )


def test_graph_preserves_two_routes_into_a_fused_candidate() -> None:
    graph = build_candidate_lineage(
        _fusion_trace(),
        qrels={"q1": {"chunk:42": 1}},
        qrel_chunk_mapping_complete=True,
    )

    passport = graph.candidates["fused:42"]
    assert set(passport.parent_candidate_ids) == {"lex:42", "vec:42"}
    assert {route.candidate_ids for route in passport.routes} == {
        ("lex:42", "fused:42"),
        ("vec:42", "fused:42"),
    }
    assert passport.outcome.kind == "relevant_retained"
    assert {(edge.source_candidate_id, edge.target_candidate_id) for edge in graph.edges} == {
        ("lex:42", "fused:42"),
        ("vec:42", "fused:42"),
    }


def test_unlabeled_production_candidate_is_unknown_not_false_positive() -> None:
    candidate = _candidate("c1", "chunk:1")
    trace = RetrievalTrace(
        trace_id="trace-production",
        service_id="search",
        run_id=None,
        query_id="q1",
        query_text="",
        pipeline_id="pipeline",
        spans=(OperatorSpan.source("retrieve", "retrieve", (candidate,)),),
        final_op_ids=("retrieve",),
    )

    passport = build_candidate_lineage(trace, qrels_for_query={}).candidates["c1"]

    assert passport.relevance.kind == "unknown"
    assert passport.outcome.kind == "unknown_relevance"


def test_missing_operator_output_marks_lineage_incomplete_not_dropped() -> None:
    candidate = _candidate("c1", "chunk:1")
    partial_input = Candidate(
        **{
            **candidate.__dict__,
            "output_rank": None,
            "decision_evidence": "unavailable",
        }
    )
    trace = RetrievalTrace(
        trace_id="trace-partial",
        service_id="search",
        run_id="run-1",
        query_id="q1",
        query_text="private",
        pipeline_id="pipeline",
        spans=(
            OperatorSpan.source("retrieve", "retrieve", (candidate,)),
            OperatorSpan(
                "filter",
                "FILTER",
                "filter",
                ("retrieve",),
                "FIRED",
                1.0,
                input_groups={"retrieve": (partial_input,)},
                outputs=(),
            ),
        ),
        final_op_ids=("filter",),
        capture=CaptureMetadata(candidates_truncated=True, lineage_evidence="partial"),
    )

    passport = build_candidate_lineage(
        trace,
        qrels_for_query={"chunk:1": 1},
        qrel_chunk_mapping_complete=True,
    ).candidates["c1"]

    assert passport.lineage_evidence == "partial"
    assert passport.outcome.kind == "lineage_incomplete"
    assert passport.outcome.operator_id == "filter"


def test_recorded_removal_and_retention_use_validated_relevance_terms() -> None:
    relevant = _candidate("relevant", "chunk:relevant", 1)
    relevant.decision_reason = "threshold"
    relevant.decision_evidence = "recorded"
    irrelevant = _candidate("irrelevant", "chunk:irrelevant", 2)
    trace = RetrievalTrace(
        trace_id="trace-outcomes",
        service_id="search",
        run_id="run-1",
        query_id="q1",
        query_text="private",
        pipeline_id="pipeline",
        spans=(
            OperatorSpan.source("retrieve", "retrieve", (relevant, irrelevant)),
            OperatorSpan(
                "filter",
                "FILTER",
                "filter",
                ("retrieve",),
                "FIRED",
                1.0,
                input_groups={"retrieve": (relevant, irrelevant)},
                outputs=(irrelevant,),
            ),
        ),
        final_op_ids=("filter",),
    )

    graph = build_candidate_lineage(
        trace,
        qrels_for_query={"chunk:relevant": 1, "chunk:irrelevant": 0},
        qrel_chunk_mapping_complete=True,
    )

    assert graph.candidates["relevant"].outcome.kind == "relevant_dropped_at_stage"
    assert graph.candidates["irrelevant"].outcome.kind == "irrelevant_retained"
