from __future__ import annotations

from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.lineage_accounting import build_stage_loss_accounting
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def _accounting_trace() -> RetrievalTrace:
    retained = Candidate(
        "chunk:kept",
        1.0,
        1,
        output_rank=1,
        candidate_id="kept",
        logical_chunk_id="chunk:kept",
    )
    removed = Candidate(
        "chunk:removed",
        0.5,
        2,
        output_rank=None,
        candidate_id="removed",
        logical_chunk_id="chunk:removed",
        decision_reason="threshold",
        decision_evidence="recorded",
    )
    return RetrievalTrace(
        trace_id="trace-accounting",
        service_id="search",
        run_id="run-1",
        query_id="q1",
        query_text="private",
        pipeline_id="pipeline",
        spans=(
            OperatorSpan.source("retrieve", "retrieve", (retained, removed)),
            OperatorSpan(
                "filter",
                "FILTER",
                "filter",
                ("retrieve",),
                "FIRED",
                1.0,
                input_groups={"retrieve": (retained, removed)},
                outputs=(retained,),
                params={"branch_id": "quality"},
            ),
        ),
        final_op_ids=("filter",),
    )


def test_stage_accounting_groups_outcomes_and_unknown_counts() -> None:
    graph = build_candidate_lineage(
        _accounting_trace(),
        qrels_for_query={"chunk:kept": 1, "chunk:removed": 0},
        qrel_chunk_mapping_complete=True,
        retrieval_entry_complete=True,
    )

    accounting = build_stage_loss_accounting(graph)

    assert accounting.relevant_retained == 1
    assert accounting.irrelevant_removed == 1
    assert accounting.by_operator["filter"].irrelevant_removed == 1
    assert accounting.by_branch["quality"].irrelevant_removed == 1
    assert accounting.unknown_relevance_count == 0
    assert accounting.incomplete_lineage_count == 0


def test_lost_upstream_requires_complete_entry_and_chunk_mapping() -> None:
    trace = _accounting_trace()
    qrels = {
        "chunk:kept": 1,
        "chunk:removed": 0,
        "chunk:never-retrieved": 2,
    }

    complete = build_stage_loss_accounting(
        build_candidate_lineage(
            trace,
            qrels_for_query=qrels,
            qrel_chunk_mapping_complete=True,
            retrieval_entry_complete=True,
        )
    )
    incomplete = build_stage_loss_accounting(
        build_candidate_lineage(
            trace,
            qrels_for_query=qrels,
            qrel_chunk_mapping_complete=False,
            retrieval_entry_complete=True,
        )
    )

    assert complete.relevant_lost_upstream == 1
    assert incomplete.relevant_lost_upstream == 0
    assert incomplete.incomplete_lineage_count == 1
