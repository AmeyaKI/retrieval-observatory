from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue


ClaimScope = Literal[
    "promotion",
    "aggregate_or_slice_evaluation",
    "lineage_diagnosis",
    "lineage_diff",
    "production_trace",
]
ReadinessStatus = Literal["READY", "HOLD", "BLOCK"]


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
