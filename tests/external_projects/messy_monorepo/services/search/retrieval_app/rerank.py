from __future__ import annotations

from typing import Any

from .models import get_cross_encoder


def rerank_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model = get_cross_encoder()
    boosts = model.predict([(query, candidate["id"]) for candidate in candidates])
    ranked = zip(candidates, boosts)
    return [candidate for candidate, _boost in sorted(ranked, key=lambda pair: (-pair[0]["score"] - pair[1], pair[0]["id"]))]
