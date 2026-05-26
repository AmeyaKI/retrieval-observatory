from __future__ import annotations

import math
from typing import Dict, List, Set


def mrr(retrieved_ids_list: List[List[str]], relevant_ids_list: List[Set[str]]) -> float:
    """Mean Reciprocal Rank across a list of queries."""
    if not retrieved_ids_list:
        return 0.0
    rr_scores = []
    for retrieved, relevant in zip(retrieved_ids_list, relevant_ids_list):
        rr = 0.0
        for rank, doc_id in enumerate(retrieved, start=1):
            if doc_id in relevant:
                rr = 1.0 / rank
                break
        rr_scores.append(rr)
    return sum(rr_scores) / len(rr_scores)


def ndcg_at_k(retrieved_ids: List[str], relevant_ids: Set[str], k: int) -> float:
    """NDCG@K with binary relevance."""
    def dcg(ids: List[str]) -> float:
        return sum(
            1.0 / math.log2(rank + 1)
            for rank, doc_id in enumerate(ids[:k], start=1)
            if doc_id in relevant_ids
        )

    actual_dcg = dcg(retrieved_ids)
    # Ideal: put all relevant docs at the top
    ideal_ids = list(relevant_ids)[:k]
    ideal_dcg = dcg(ideal_ids + [""] * k)  # pad — irrelevant docs contribute 0
    # Recompute ideal correctly
    n_ideal = min(k, len(relevant_ids))
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, n_ideal + 1))

    if ideal_dcg == 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


def average_precision(retrieved_ids: List[str], relevant_ids: Set[str]) -> float:
    if not relevant_ids:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            hits += 1
            precision_sum += hits / rank
    if hits == 0:
        return 0.0
    return precision_sum / len(relevant_ids)


def map_score(retrieved_ids_list: List[List[str]], relevant_ids_list: List[Set[str]]) -> float:
    """Mean Average Precision across queries."""
    if not retrieved_ids_list:
        return 0.0
    ap_scores = [
        average_precision(r, rel)
        for r, rel in zip(retrieved_ids_list, relevant_ids_list)
    ]
    return sum(ap_scores) / len(ap_scores)


def ndcg_at_k_graded(retrieved_ids: List[str], graded_qrels: Dict[str, int], k: int) -> float:
    """NDCG@K with graded relevance using standard exponential gain (2^grade - 1).

    Matches the BEIR benchmark methodology (Thakur et al. 2021) and pytrec_eval.
    gain(grade=1) = 1, gain(grade=2) = 3, gain(grade=3) = 7, etc.
    """
    if not graded_qrels:
        return 0.0

    actual_dcg = sum(
        (2 ** graded_qrels.get(doc_id, 0) - 1) / math.log2(rank + 1)
        for rank, doc_id in enumerate(retrieved_ids[:k], start=1)
    )
    ideal_grades = sorted(graded_qrels.values(), reverse=True)[:k]
    ideal_dcg = sum(
        (2 ** g - 1) / math.log2(rank + 1)
        for rank, g in enumerate(ideal_grades, start=1)
        if g > 0
    )
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0
