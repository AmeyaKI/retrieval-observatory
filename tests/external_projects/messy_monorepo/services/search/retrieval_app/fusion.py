from __future__ import annotations

from typing import Any


def fuse_results(keyword_hits: list[dict[str, Any]], vector_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    for hits in (keyword_hits, vector_hits):
        for rank, hit in enumerate(hits):
            scores[hit["id"]] = scores.get(hit["id"], 0.0) + 1.0 / (60 + rank)
    return [{"id": doc_id, "score": score} for doc_id, score in sorted(scores.items(), key=lambda item: -item[1])]
