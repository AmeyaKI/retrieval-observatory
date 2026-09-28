from __future__ import annotations

from typing import Any

from retrieval_app.corpus import DOCUMENTS


def vector_search(query: str) -> list[dict[str, Any]]:
    scored = sorted(DOCUMENTS, key=lambda doc: -len(set(query.lower()) & set(doc["text"].lower())))
    return [{"id": doc["id"], "score": 0.5 / (rank + 1)} for rank, doc in enumerate(scored[:2])]
