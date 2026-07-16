from __future__ import annotations

from typing import Protocol, TypeAlias

from retrieval_observatory.diagnostics.model import DiagnosticContext, DiagnosticFinding

RuleResult: TypeAlias = DiagnosticFinding


class DiagnosticRule(Protocol):
    label: str
    method_id: str
    method_version: str

    def evaluate(self, context: DiagnosticContext) -> RuleResult: ...
