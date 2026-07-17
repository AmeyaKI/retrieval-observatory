from __future__ import annotations

from copy import copy
from typing import Iterable, Sequence

from retrieval_observatory.diagnostics.history import CandidateHistoryIndex
from retrieval_observatory.diagnostics.identity_rules import QrelAbsentFromCorpusRule, SourceMissRule
from retrieval_observatory.diagnostics.model import DiagnosticContext, DiagnosticFinding
from retrieval_observatory.diagnostics.routing_rules import BranchSpecificMissRule, GateExclusionRule
from retrieval_observatory.diagnostics.transition_rules import (
    FilterLossRule,
    FinalRankingFailureRule,
    FusionLossRule,
    RerankerLossRule,
    TruncationLossRule,
)
from retrieval_observatory.tracing.model import RetrievalTrace


class DiagnosticEngine:
    def __init__(self, rules: Sequence) -> None:
        self._rules = tuple(rules)

    @classmethod
    def default(cls) -> "DiagnosticEngine":
        return cls((
            QrelAbsentFromCorpusRule(), SourceMissRule(), BranchSpecificMissRule(), GateExclusionRule(),
            FusionLossRule(), FilterLossRule(), RerankerLossRule(), TruncationLossRule(),
            FinalRankingFailureRule(),
        ))

    @property
    def rule_labels(self) -> tuple[str, ...]:
        return tuple(rule.label for rule in self._rules)

    def evaluate(self, context: DiagnosticContext) -> tuple[DiagnosticFinding, ...]:
        findings = tuple(copy(rule).evaluate(context) for rule in self._rules)
        for finding in findings:
            context.validate_finding(finding)
        return findings


def context_for_trace(
    trace: RetrievalTrace,
    *,
    relevant_document_ids: Iterable[str] = (),
    corpus_document_ids: Iterable[str] | None = None,
    cutoff: int = 10,
) -> DiagnosticContext:
    history = CandidateHistoryIndex.build(trace)
    return DiagnosticContext(
        trace=trace,
        relevant_document_ids=frozenset(relevant_document_ids),
        corpus_document_ids=frozenset(corpus_document_ids) if corpus_document_ids is not None else None,
        cutoff=cutoff,
        candidate_histories=history.by_document,
        capture_complete=history.complete,
    )
