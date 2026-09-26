"""A deterministic stand-in for a cross-encoder. This is the RERANK operator; its parent is ``fusion.py``."""
from __future__ import annotations

from retrieval_observatory.sdk.observe import observe
from retrievers import tokens


class OverlapReranker:
    """Phrase bonus plus token overlap, standing in for a cross-encoder."""

    @observe("RERANK", op_id="rerank", parent_ids=("rrf",), replay_policy="OBSERVED_ABLATION")
    def rerank(self, query: str, candidates: list[dict], *, k: int = 5) -> list[dict]:
        query_tokens = tokens(query)
        scored = [
            {
                "doc_id": hit["doc_id"],
                "score": len(query_tokens & tokens(hit["text"])) + (1.0 if query.lower() in hit["text"].lower() else 0.0),
                "text": hit["text"],
            }
            for hit in candidates
        ]
        scored.sort(key=lambda hit: (-hit["score"], hit["doc_id"]))
        return scored[:k]
