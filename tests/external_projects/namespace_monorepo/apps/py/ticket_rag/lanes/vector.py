from __future__ import annotations

from typing import Any

from ticket_rag.corpus import DOCUMENTS


def vector_search(query: str) -> list[dict[str, Any]]:
    return [{"id": doc["id"], "score": float(len(set(query) & set(doc["text"])))} for doc in DOCUMENTS]
