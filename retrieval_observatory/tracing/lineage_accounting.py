from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from retrieval_observatory.tracing.lineage import CandidateLineageGraph, OutcomeKind

_OUTCOMES: tuple[OutcomeKind, ...] = (
    "relevant_retained",
    "irrelevant_removed",
    "irrelevant_retained",
    "relevant_lost_upstream",
    "relevant_dropped_at_stage",
    "unknown_relevance",
    "lineage_incomplete",
)


@dataclass(frozen=True)
class OutcomeCounts:
    relevant_retained: int = 0
    irrelevant_removed: int = 0
    irrelevant_retained: int = 0
    relevant_lost_upstream: int = 0
    relevant_dropped_at_stage: int = 0
    unknown_relevance: int = 0
    lineage_incomplete: int = 0


@dataclass(frozen=True)
class StageLossAccounting(OutcomeCounts):
    by_operator: Mapping[str, OutcomeCounts] = field(default_factory=dict)
    by_branch: Mapping[str, OutcomeCounts] = field(default_factory=dict)
    by_evidence: Mapping[str, OutcomeCounts] = field(default_factory=dict)
    unknown_relevance_count: int = 0
    incomplete_lineage_count: int = 0


def _counts(values: Mapping[str, int]) -> OutcomeCounts:
    return OutcomeCounts(**{outcome: int(values.get(outcome, 0)) for outcome in _OUTCOMES})


def _increment(group: dict[str, dict[str, int]], key: str, outcome: OutcomeKind) -> None:
    group.setdefault(key, {})[outcome] = group.setdefault(key, {}).get(outcome, 0) + 1


def build_stage_loss_accounting(graph: CandidateLineageGraph) -> StageLossAccounting:
    totals: dict[str, int] = {}
    by_operator: dict[str, dict[str, int]] = {}
    by_branch: dict[str, dict[str, int]] = {}
    by_evidence: dict[str, dict[str, int]] = {}

    for passport in graph.candidates.values():
        if passport.derived_child_ids:
            continue
        outcome = passport.outcome
        totals[outcome.kind] = totals.get(outcome.kind, 0) + 1
        operator_id = outcome.operator_id
        branch_id = outcome.branch_id
        if operator_id is None and passport.routes and passport.routes[0].stages:
            final_stage = passport.routes[0].stages[-1]
            operator_id = final_stage.op_id
            branch_id = final_stage.branch_id
        _increment(by_operator, operator_id or "unavailable", outcome.kind)
        _increment(by_branch, branch_id or "unassigned", outcome.kind)
        _increment(by_evidence, outcome.evidence, outcome.kind)

    unseen_relevant = {
        chunk_id
        for chunk_id, grade in graph.qrels_for_query.items()
        if int(grade) > 0 and chunk_id not in graph.observed_logical_chunk_ids
    }
    for _ in unseen_relevant:
        if graph.qrel_chunk_mapping_complete and graph.retrieval_entry_complete:
            outcome: OutcomeKind = "relevant_lost_upstream"
            evidence = "recorded"
        else:
            outcome = "lineage_incomplete"
            evidence = "partial"
        totals[outcome] = totals.get(outcome, 0) + 1
        _increment(by_operator, "retrieval_entry", outcome)
        _increment(by_branch, "unassigned", outcome)
        _increment(by_evidence, evidence, outcome)

    total_counts = _counts(totals)
    return StageLossAccounting(
        **total_counts.__dict__,
        by_operator={key: _counts(value) for key, value in sorted(by_operator.items())},
        by_branch={key: _counts(value) for key, value in sorted(by_branch.items())},
        by_evidence={key: _counts(value) for key, value in sorted(by_evidence.items())},
        unknown_relevance_count=total_counts.unknown_relevance,
        incomplete_lineage_count=total_counts.lineage_incomplete,
    )
