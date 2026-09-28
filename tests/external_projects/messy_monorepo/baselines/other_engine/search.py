"""A comparison system's own search tool, checked in for side-by-side runs; not part of the pipeline."""
from __future__ import annotations


def search(query: str) -> list[dict[str, str]]:
    return [{"id": "other-engine", "text": query}]
