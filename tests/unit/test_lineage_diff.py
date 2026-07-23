from retrieval_observatory.release.readiness import ClaimReadiness, EvidenceFinding
from retrieval_observatory.tracing.lineage import (
    CandidateLineageGraph,
    CandidateOutcome,
    CandidatePassport,
    CandidateRoute,
    CandidateSource,
    CandidateStage,
    RelevanceEvidence,
)
from retrieval_observatory.tracing.lineage_diff import diff_candidate_lineage


def _readiness(status: str = "READY") -> ClaimReadiness:
    findings = []
    if status != "READY":
        findings = [
            EvidenceFinding(
                code="lineage_topology_unaligned",
                scope="lineage_diff",
                status="BLOCK",
                observed="different topology",
                required="aligned topology",
                detail="Stage semantics are not aligned.",
                next_action="Inspect both recorded paths side by side.",
            )
        ]
    return ClaimReadiness(scope="lineage_diff", status=status, findings=findings)


def _graph(
    *,
    revision: str = "rev-1",
    removed_at: str | None = "filter-a",
    final: bool = False,
    rank: int = 2,
    topology: str = "topology-1",
) -> CandidateLineageGraph:
    stage = CandidateStage("retrieve", "SOURCE", None, rank, 0.8, {})
    passport = CandidatePassport(
        candidate_id="candidate-1",
        logical_chunk_id="chunk-1",
        source=CandidateSource("doc-1", revision, None, 0, 20, None),
        parent_candidate_ids=(),
        routes=(CandidateRoute(("candidate-1",), ("retrieve",), (), (stage,), "recorded"),),
        relevance=RelevanceEvidence("relevant", 1, "validated"),
        outcome=CandidateOutcome(
            "relevant_retained" if final else "relevant_dropped_at_stage",
            "recorded",
            operator_id=removed_at,
            reason="threshold" if removed_at else None,
        ),
        lineage_evidence="recorded",
        final_context_member=final,
        removed_at=removed_at,
        removal_reason="threshold" if removed_at else None,
        removal_evidence="recorded" if removed_at else "unavailable",
    )
    return CandidateLineageGraph(
        trace_id="trace-1",
        run_id="run-1",
        query_id="q-1",
        pipeline_id="pipeline-1",
        topology_hash=topology,
        candidates={"candidate-1": passport},
        edges=(),
    )


def test_diff_highlights_exit_change_for_aligned_chunk() -> None:
    result = diff_candidate_lineage(
        _graph(removed_at="filter-a"),
        _graph(removed_at="filter-b"),
        readiness=_readiness(),
    )

    assert result.status == "READY"
    assert result.changed[0].kind == "exit_changed"
    assert result.changed[0].logical_chunk_id == "chunk-1"


def test_unaligned_document_revisions_block_stage_diff_but_keep_sides() -> None:
    result = diff_candidate_lineage(
        _graph(revision="rev-a"),
        _graph(revision="rev-b"),
        readiness=_readiness("BLOCK"),
    )

    assert result.status == "BLOCK"
    assert result.baseline is not None and result.candidate is not None
    assert result.changed == ()


def test_diff_reports_retention_rank_and_branch_changes_without_causal_claims() -> None:
    baseline = _graph(final=False, rank=4, removed_at="filter")
    candidate = _graph(final=True, rank=1, removed_at=None)

    result = diff_candidate_lineage(baseline, candidate, readiness=_readiness())

    assert {change.kind for change in result.changed} >= {
        "newly_retained",
        "rank_shifted",
        "exit_changed",
    }
    assert all("cause" not in change.detail.lower() for change in result.changed)
