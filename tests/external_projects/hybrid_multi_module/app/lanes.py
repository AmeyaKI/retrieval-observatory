from __future__ import annotations

from typing import Any


def _candidate(doc_id: str, score: float, rank: int) -> dict[str, Any]:
    return {"id": doc_id, "score": score, "rank": rank}


class LexicalLane:
    def search(self, query: str, route: str) -> list[dict[str, Any]]:
        return [_candidate("d-shared", 0.84, 1), _candidate("d-lexical", 0.79, 2), _candidate("d-stale", 0.41, 3)]


class DenseLane:
    async def search(self, query: str, route: str) -> list[dict[str, Any]]:
        return [_candidate("d-dense", 0.88, 1), _candidate("d-shared", 0.83, 2)]
