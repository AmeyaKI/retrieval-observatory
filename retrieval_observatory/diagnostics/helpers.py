from __future__ import annotations

from typing import Iterable

from retrieval_observatory.diagnostics.model import DiagnosticContext, DiagnosticEvidence, DiagnosticFinding, FindingAvailability


def finding(rule, availability: FindingAvailability, *, documents: Iterable[str] = (), operators: Iterable[str] = (), reason: str | None = None, limitations: Iterable[str] = (), details: dict | None = None) -> DiagnosticFinding:
    evidence = None
    if availability in {FindingAvailability.SUPPORTED, FindingAvailability.LIMITED}:
        evidence = DiagnosticEvidence(
            evidence_class="measured_candidate_transition",
            method_id=rule.method_id,
            method_version=rule.method_version,
            trace_ids=(rule._context.trace.trace_id,),
            operator_ids=tuple(sorted(set(operators))),
            document_ids=tuple(sorted(set(documents))),
            cutoff=rule._context.cutoff,
            limitations=tuple(limitations),
        )
    return DiagnosticFinding(rule.label, availability, evidence, reason, details or {})


class RuleBase:
    method_id = "candidate_transition"
    method_version = "1.0"

    def bind(self, context: DiagnosticContext):
        self._context = context
        return self

    def unavailable(self, reason: str) -> DiagnosticFinding:
        return finding(self, FindingAvailability.UNAVAILABLE, reason=reason)

    def not_observed(self) -> DiagnosticFinding:
        return finding(self, FindingAvailability.NOT_OBSERVED)
