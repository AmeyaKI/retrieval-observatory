from __future__ import annotations

from typing import Any

from ..corpus import DOCUMENTS


def filter_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if candidate["score"] > 0]


def keyword_search(query: str) -> list[dict[str, Any]]:
    terms = set(query.lower().split())
    hits = [doc for doc in DOCUMENTS if terms & set(doc["text"].lower().split())]
    return filter_candidates([{"id": doc["id"], "score": 1.0 / (rank + 1)} for rank, doc in enumerate(hits)])
