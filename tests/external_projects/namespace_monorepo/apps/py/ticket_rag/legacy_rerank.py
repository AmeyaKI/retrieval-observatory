from __future__ import annotations

from typing import Any


def rerank_results(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda candidate: -candidate["score"])
