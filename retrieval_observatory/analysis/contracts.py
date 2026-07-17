from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

AnalysisState = Literal["ready", "partial", "unavailable"]
EvidenceClass = Literal["measured", "statistical", "replayed", "heuristic", "inferred", "unavailable"]
T = TypeVar("T")


@dataclass(frozen=True)
class AnalysisScope:
    db_id: str
    service_id: str | None = None
    run_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    cohort_id: str | None = None


@dataclass(frozen=True)
class EvidenceDescriptor:
    evidence_class: EvidenceClass
    method_id: str
    method_version: str
    sample_size: int
    population_size: int
    coverage: float
    thresholds: dict[str, float | int | str] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    supporting_trace_ids: tuple[str, ...] = ()
    supporting_query_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sample_size < 0 or self.population_size < 0 or self.sample_size > self.population_size:
            raise ValueError("invalid analysis sample size")
        if not 0 <= self.coverage <= 1:
            raise ValueError("analysis coverage must be between 0 and 1")


@dataclass(frozen=True)
class AnalysisResult(Generic[T]):
    state: AnalysisState
    scope: AnalysisScope
    evidence: EvidenceDescriptor
    data: T | None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.state == "ready" and (self.data is None or self.evidence.sample_size == 0):
            raise ValueError("ready analysis requires data and a nonzero sample")
        if self.state == "partial" and (
            self.data is None or not self.evidence.limitations or self.evidence.coverage >= 1
        ):
            raise ValueError("partial analysis requires data, limitations, and incomplete coverage")
        if self.state == "unavailable" and (
            self.data is not None or not self.unavailable_reason or self.evidence.evidence_class != "unavailable"
        ):
            raise ValueError("unavailable analysis requires no data and an explicit reason")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def unavailable(scope: AnalysisScope, method_id: str, reason: str) -> AnalysisResult[Any]:
    return AnalysisResult(
        "unavailable", scope, EvidenceDescriptor("unavailable", method_id, "1", 0, 0, 0), None, reason
    )


def result(
    scope: AnalysisScope,
    method_id: str,
    data: T,
    sample: int,
    population: int | None = None,
    *,
    evidence_class: EvidenceClass = "measured",
    limitations: tuple[str, ...] = (),
    trace_ids: tuple[str, ...] = (),
) -> AnalysisResult[T]:
    population = sample if population is None else population
    coverage = sample / population if population else 0
    state: AnalysisState = "partial" if limitations or coverage < 1 else "ready"
    return AnalysisResult(
        state,
        scope,
        EvidenceDescriptor(
            evidence_class,
            method_id,
            "1",
            sample,
            population,
            coverage,
            limitations=limitations,
            supporting_trace_ids=trace_ids,
        ),
        data,
    )
