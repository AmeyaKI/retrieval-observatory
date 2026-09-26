"""Reciprocal rank fusion. This is the FUSE operator; its parents live in ``retrievers.py``."""
from __future__ import annotations

from retrieval_observatory.sdk.observe import observe


@observe("FUSE", op_id="rrf", parent_ids=("keyword", "dense"), deterministic=True, replay_policy="EXACT")
def rrf_merge(lanes: list[list[dict]], *, rrf_k: int = 60) -> list[dict]:
    """Merge ranked lists with ``1 / (rrf_k + rank)``.

    ``rrf_k`` is keyword-only so the call site records it as a span param.
    """
    scores: dict[str, float] = {}
    texts: dict[str, str] = {}
    for hits in lanes:
        for rank, hit in enumerate(hits, start=1):
            scores[hit["doc_id"]] = scores.get(hit["doc_id"], 0.0) + 1.0 / (rrf_k + rank)
            texts[hit["doc_id"]] = hit["text"]
    ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
    return [{"doc_id": doc_id, "score": scores[doc_id], "text": texts[doc_id]} for doc_id in ordered]
