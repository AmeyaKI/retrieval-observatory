"""Weekly usage reports; unrelated to the retrieval pipeline."""
from __future__ import annotations

from typing import Any


def filter_bots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not row.get("is_bot")]


def filter_by_week(rows: list[dict[str, Any]], week: int) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("week") == week]


def rank_by_clicks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: -row.get("clicks", 0))


def rerank_pages(query: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(pages, key=lambda page: -page.get("views", 0))
