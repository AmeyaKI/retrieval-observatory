"""Query-intent helpers the pipeline calls; predicates and formatters, not operators."""
from __future__ import annotations


def has_task_intent(query: str) -> bool:
    return query.lower().startswith(("how", "set up"))


def range_intent(query: str):
    return "between" in query.lower()


def format_gate_value(value: object) -> str:
    return f"gate={value}"
