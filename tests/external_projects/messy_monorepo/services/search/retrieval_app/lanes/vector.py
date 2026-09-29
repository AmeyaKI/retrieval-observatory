from __future__ import annotations

from typing import Any

from retrieval_app.corpus import DOCUMENTS


def filter_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return candidates[:2]


def vector_search(query: str) -> list[dict[str, Any]]:
    scored = sorted(DOCUMENTS, key=lambda doc: -len(set(query.lower()) & set(doc["text"].lower())))
    return filter_candidates([{"id": doc["id"], "score": 0.5 / (rank + 1)} for rank, doc in enumerate(scored)])
