"""Typed journey records: one row per (query, evaluation entity), events underneath.

Every field is descriptive (see ``docs/rebuild/EVIDENCE_CONTRACT.md``): membership, rank,
judgment and capture completeness are recorded independently and never collapsed into each
other. Rows are plain data; ``to_dict``/``from_dict`` round-trip through JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

from retrieval_observatory.datasets.judgments import EvaluationUnit

JOURNEY_SCHEMA_VERSION = 1
DERIVATION_VERSION = "journeys-1"

EventKind = Literal["introduced", "retained", "promoted", "demoted", "removed", "recovered", "transformed", "unknown"]
ReasonEvidence = Literal["recorded", "inferred", "unavailable"]
InputEvidence = Literal["recorded", "positional", "inferred", "unavailable", "not_applicable"]
JudgmentState = Literal["relevant", "nonrelevant", "unjudged", "unmapped"]
Membership = Literal["included", "excluded", "unknown"]
Confusion = Literal["TP", "FP", "FN", "TN", "unknown"]
CaptureState = Literal["complete", "partial"]
Outcome = Literal[
    "relevant_delivered",
    "relevant_excluded",
    "retained_below_cutoff",
    "not_observed",
    "judged_nonrelevant",
    "unjudged",
    "insufficient_evidence",
]


@dataclass(frozen=True)
class JourneyEvent:
    op_id: str
    operator_id: str
    invocation_id: str | None
    branch: str | None
    occurrence_entity_id: str
    candidate_id: str
    kind: EventKind
    input_present: bool
    output_present: bool
    input_rank: int | None
    output_rank: int | None
    input_occurrences: int
    reason: str | None
    reason_evidence: ReasonEvidence
    boundary_complete: bool
    input_evidence: InputEvidence
    source_occurrences: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "source_occurrences": list(self.source_occurrences)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> JourneyEvent:
        return cls(**{**value, "source_occurrences": tuple(value.get("source_occurrences", ()))})


@dataclass(frozen=True)
class JourneyRow:
    schema_version: int
    derivation_version: str
    run_id: str | None
    pipeline_id: str
    trace_id: str
    query_id: str
    namespace: str
    entity_id: str
    unit: EvaluationUnit
    entity_revision: str | None
    judgment: JudgmentState
    grade: int | None
    judgment_source: str | None
    final_membership: Membership
    in_final_output: bool | None
    final_rank: int | None
    outcome: Outcome
    confusion: Confusion
    capture_state: CaptureState
    observed: bool
    loss_boundary: str | None
    priority: int
    events: tuple[JourneyEvent, ...]
    occurrence_entity_ids: tuple[str, ...]
    evaluation_digest: str
    judgment_digest: str
    trace_digest: str
    investigation_link: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [event.to_dict() for event in self.events]
        payload["occurrence_entity_ids"] = list(self.occurrence_entity_ids)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> JourneyRow:
        return cls(
            **{
                **value,
                "events": tuple(JourneyEvent.from_dict(event) for event in value.get("events", ())),
                "occurrence_entity_ids": tuple(value.get("occurrence_entity_ids", ())),
            }
        )
