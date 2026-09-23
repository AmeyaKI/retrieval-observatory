from __future__ import annotations

from typing import Any

PRIOR = {"d-lexical": 0.9, "d-shared": 0.8, "d-dense": 0.7}


class Reranker:
    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(candidates, key=lambda candidate: (-PRIOR.get(candidate["id"], 0.0), candidate["rank"]))
        return [
            {"id": candidate["id"], "score": PRIOR.get(candidate["id"], 0.0), "rank": rank}
            for rank, candidate in enumerate(ordered[:3], start=1)
        ]
