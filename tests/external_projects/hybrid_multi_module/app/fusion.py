from __future__ import annotations

from typing import Any

RRF_K = 60


def rrf_fusion(*lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reciprocal-rank fusion over the lanes that ran; one candidate per id, ranks reassigned."""
    fused: dict[str, float] = {}
    for lane in lanes:
        for candidate in lane:
            fused[candidate["id"]] = fused.get(candidate["id"], 0.0) + 1.0 / (RRF_K + candidate["rank"])
    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return [{"id": doc_id, "score": round(score, 6), "rank": rank} for rank, (doc_id, score) in enumerate(ordered, start=1)]
