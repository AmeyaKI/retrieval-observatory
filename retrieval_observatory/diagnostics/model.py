from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from retrieval_observatory.tracing.model import RetrievalTrace


class FindingAvailability(str, Enum):
    SUPPORTED = "supported"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    NOT_OBSERVED = "not_observed"


@dataclass(frozen=True)
class DiagnosticEvidence:
    evidence_class: str
    method_id: str
    method_version: str
    trace_ids: tuple[str, ...] = ()
    operator_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    cutoff: int | None = None
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiagnosticEvidence":
        return cls(
            **{
                **value,
                "trace_ids": tuple(value.get("trace_ids", ())),
                "operator_ids": tuple(value.get("operator_ids", ())),
                "document_ids": tuple(value.get("document_ids", ())),
                "limitations": tuple(value.get("limitations", ())),
            }
        )


@dataclass(frozen=True)
class DiagnosticFinding:
    label: str
    availability: FindingAvailability
    evidence: DiagnosticEvidence | None = None
    unavailable_reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.availability in {FindingAvailability.SUPPORTED, FindingAvailability.LIMITED} and self.evidence is None:
            raise ValueError("supported and limited findings require evidence")
        if self.availability is FindingAvailability.UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("unavailable_reason is required")
        if self.availability is FindingAvailability.NOT_OBSERVED and self.unavailable_reason:
            raise ValueError("not-observed findings cannot have unavailable_reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "availability": self.availability.value,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "unavailable_reason": self.unavailable_reason,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiagnosticFinding":
        return cls(
            str(value["label"]),
            FindingAvailability(value["availability"]),
            DiagnosticEvidence.from_dict(value["evidence"]) if value.get("evidence") else None,
            value.get("unavailable_reason"),
            dict(value.get("details", {})),
        )


@dataclass(frozen=True)
class DiagnosticContext:
    trace: RetrievalTrace
    relevant_document_ids: frozenset[str]
    cutoff: int
    corpus_document_ids: frozenset[str] | None = None
    candidate_histories: Mapping[str, Any] = field(default_factory=dict)
    capture_complete: bool = True

    def __post_init__(self) -> None:
        if self.cutoff < 1:
            raise ValueError("cutoff must be positive")

    def validate_finding(self, finding: DiagnosticFinding) -> None:
        if not finding.evidence:
            return
        unknown_traces = set(finding.evidence.trace_ids) - {self.trace.trace_id}
        if unknown_traces:
            raise ValueError(f"evidence references unknown trace: {', '.join(sorted(unknown_traces))}")
        known_ops = {span.op_id for span in self.trace.spans}
        unknown_ops = set(finding.evidence.operator_ids) - known_ops
        if unknown_ops:
            raise ValueError(f"evidence references unknown operator: {', '.join(sorted(unknown_ops))}")
