"""Aggregates benchmark results for the weekly report."""
from __future__ import annotations

from typing import Any


def aggregate_by_system_and_category(rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["system"], row["category"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def filter_rows_by_system(rows: list[dict[str, Any]], system: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["system"] == system]
