from __future__ import annotations

from typing import Dict, List

from retrieval_observatory.types import StageSnapshot

# Cost per 1000 API calls (searches/reranks)
_PRICING: Dict[str, float] = {
    "cohere/rerank-english-v3.0": 0.002,
    "cohere/rerank-multilingual-v3.0": 0.002,
    "cohere/rerank-english-v2.0": 0.001,
    "openai/gpt-4o-mini": 0.00015,  # per 1k input tokens (approx)
    "openai/gpt-4o": 0.005,
}


def estimate_cost(
    stage_snapshots: List[StageSnapshot],
    provider: str,
    model: str,
    n_docs_per_call: int = 100,
) -> float:
    """Estimate API cost for reranker stages.

    Returns total estimated cost in USD.
    """
    key = f"{provider}/{model}"
    price_per_1k = _PRICING.get(key)
    if price_per_1k is None:
        raise ValueError(
            f"Unknown provider/model '{key}'. Known: {list(_PRICING.keys())}"
        )
    n_calls = len(stage_snapshots)
    return n_calls * price_per_1k / 1000 * n_docs_per_call
