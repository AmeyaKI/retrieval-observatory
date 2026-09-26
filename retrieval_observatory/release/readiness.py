from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


ClaimScope = Literal[
    "promotion",
    "aggregate_or_slice_evaluation",
    "lineage_diagnosis",
    "lineage_diff",
    "production_trace",
]
ReadinessStatus = Literal["READY", "HOLD", "BLOCK"]
ProvenanceClassification = Literal["invariant", "expected", "unexpected", "evidence_invalid", "unknown"]


class EvidenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    scope: ClaimScope
    status: ReadinessStatus
    observed: JsonValue | None = None
    required: JsonValue | None = None
    detail: str
    next_action: str


class ClaimReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope: ClaimScope
    status: ReadinessStatus
    findings: list[EvidenceFinding]


class FieldComparison(BaseModel):
    """One manifest field compared across baseline and candidate, with its classification."""

    model_config = ConfigDict(extra="forbid", strict=True)

    field: str
    baseline: Any
    candidate: Any
    equal: bool
    classification: ProvenanceClassification
    finding_code: str | None = None


class ProvenanceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    invariants: list[FieldComparison] = Field(default_factory=list)
    interventions: list[FieldComparison] = Field(default_factory=list)
    consistency: list[FieldComparison] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
