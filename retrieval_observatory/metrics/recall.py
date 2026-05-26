from __future__ import annotations

import math
from datetime import datetime
from typing import List, Literal, Set

from retrieval_observatory.types import Document


def recall_at_k(retrieved_ids: List[str], relevant_ids: Set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be > 0")
    if not relevant_ids:
        return 0.0
    hits = len(set(retrieved_ids[:k]) & relevant_ids)
    return hits / len(relevant_ids)


def temporal_recall_at_k(
    retrieved: List[Document],
    relevant_ids: Set[str],
    k: int,
    query_anchor: datetime,
    decay: Literal["exponential", "linear", "step"] = "exponential",
    reference_period_days: float = 30.0,
    decay_rate: float = 1.0,
) -> float:
    """Time-decay weighted Recall@K.

    TemporalRecall@K = Σ(w_i for retrieved[:K] ∩ relevant) / Σ(w_i for all relevant)

    Documents without a timestamp receive weight 1.0 (neutral).
    """
    if k <= 0:
        raise ValueError("k must be > 0")
    if not relevant_ids:
        return 0.0

    T = reference_period_days * 86400  # seconds

    def weight(doc: Document) -> float:
        if doc.timestamp is None:
            return 1.0
        delta_s = abs((doc.timestamp - query_anchor).total_seconds())
        if decay == "exponential":
            return math.exp(-decay_rate * delta_s / T)
        elif decay == "linear":
            return max(0.0, 1.0 - delta_s / T)
        else:  # step
            return 1.0 if delta_s <= T else 0.0

    # Build a lookup for all retrieved docs
    retrieved_k = retrieved[:k]
    retrieved_map = {d.id: d for d in retrieved_k}

    # Numerator: weights for retrieved[:k] ∩ relevant
    numerator = sum(
        weight(retrieved_map[doc_id])
        for doc_id in relevant_ids
        if doc_id in retrieved_map
    )

    # Denominator: weights for all relevant docs. For relevant docs outside top-K
    # we apply neutral weight=1.0 to avoid denominator coupling to deep-list retrieval.
    denominator = sum(
        weight(retrieved_map[doc_id]) if doc_id in retrieved_map else 1.0
        for doc_id in relevant_ids
    )

    if denominator == 0.0:
        return 0.0
    return numerator / denominator
