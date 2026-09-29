"""Operator utility: find support tickets that mention a phrase."""
from __future__ import annotations

TICKETS = [{"id": "t-1", "title": "Widget pricing question"}]


def search_tickets(query: str) -> list[dict[str, str]]:
    return [ticket for ticket in TICKETS if query.lower() in ticket["title"].lower()]
