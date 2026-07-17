from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

PredicateOperator = Literal["eq", "ne", "in", "gte", "lte", "contains", "exists"]
_ROOTS = {
    "query.id",
    "query.text",
    "trace.status",
    "trace.service",
    "trace.pipeline_id",
    "trace.topology_id",
    "trace.total_latency_ms",
    "diagnostic.label",
    "route.value",
}


@dataclass(frozen=True)
class CohortClause:
    field: str
    operator: PredicateOperator
    value: Any = None


@dataclass(frozen=True)
class CohortDefinition:
    cohort_id: str
    name: str
    version: int
    clauses: tuple[CohortClause, ...]
    conjunction: Literal["all", "any"] = "all"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_cohort(value: CohortDefinition) -> None:
    if not value.cohort_id or not value.name or value.version < 1 or not value.clauses:
        raise ValueError("cohort identity, version, and clauses are required")
    for clause in value.clauses:
        if clause.field not in _ROOTS and not clause.field.startswith(("query.metadata.", "trace.metadata.")):
            raise ValueError(f"field is not allowed: {clause.field}")
        if clause.operator not in {"eq", "ne", "in", "gte", "lte", "contains", "exists"}:
            raise ValueError(f"operator is not allowed: {clause.operator}")


def _get(record: Mapping[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def matches_cohort(record: Mapping[str, Any], definition: CohortDefinition) -> bool:
    validate_cohort(definition)

    def match(clause: CohortClause) -> bool:
        actual = _get(record, clause.field)
        expected = clause.value
        return {
            "eq": lambda: actual == expected,
            "ne": lambda: actual != expected,
            "in": lambda: actual in expected,
            "gte": lambda: actual is not None and actual >= expected,
            "lte": lambda: actual is not None and actual <= expected,
            "contains": lambda: actual is not None and expected in actual,
            "exists": lambda: (actual is not None) == bool(expected if expected is not None else True),
        }[clause.operator]()

    values = [match(clause) for clause in definition.clauses]
    return all(values) if definition.conjunction == "all" else any(values)
