from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional, Set

from retrieval_observatory.forge.types import SyntheticQuery


def build_extractive_qrels(queries: List[SyntheticQuery]) -> Dict[str, Dict[str, int]]:
    """Build qrels from extractive ground truth — source doc is always grade 2.

    This is the default, cost-free method. For each generated query, the
    document(s) it was generated from are treated as highly relevant (grade 2).
    """
    qrels: Dict[str, Dict[str, int]] = {}
    for q in queries:
        q.metadata.setdefault("label_method", "extractive_source_document")
        qrels[q.query_id] = {doc_id: 2 for doc_id in q.positive_doc_ids}
    return qrels


def _bm25_top_k(
    query_text: str,
    corpus: Dict[str, Dict],
    k: int = 20,
    exclude_ids: Optional[Set[str]] = None,
) -> List[str]:
    """Return top-K doc IDs by simple TF-IDF-like scoring (no rank-bm25 dependency)."""
    query_tokens = set(re.findall(r"\b[a-z]{3,}\b", query_text.lower()))
    if not query_tokens:
        return []

    scores: Dict[str, float] = {}
    for doc_id, doc in corpus.items():
        if exclude_ids and doc_id in exclude_ids:
            continue
        text = (doc.get("text", "") + " " + doc.get("title", "")).lower()
        doc_tokens = text.split()
        if not doc_tokens:
            continue
        tf = sum(doc_tokens.count(t) for t in query_tokens) / len(doc_tokens)
        scores[doc_id] = tf

    return sorted(scores, key=scores.__getitem__, reverse=True)[:k]


async def validate_qrels_with_llm(
    queries: List[SyntheticQuery],
    corpus: Dict[str, Dict],
    judge,  # LLMJudge protocol from datasets/llm_judge.py
    top_k: int = 20,
    budget: int = 1000,
    batch_size: int = 8,
) -> Dict[str, Dict[str, int]]:
    """Expand extractive qrels by LLM-validating BM25 top-K candidates.

    Uses the existing LLMJudge protocol (GeminiJudge etc.) to find additional
    relevant documents beyond the extractive ground truth. Results are merged
    with extractive labels — extractive always wins (grade 2 preserved).

    Args:
        queries: Generated synthetic queries.
        corpus: The corpus being evaluated.
        judge: Any LLMJudge instance (GeminiJudge, OpenAIJudge, AnthropicJudge).
        top_k: Number of BM25 candidates to validate per query.
        budget: Max total LLM calls before stopping validation.
        batch_size: Concurrent LLM calls per batch.

    Returns:
        Merged qrels dict (query_id -> {doc_id -> grade}).
    """
    # Start with extractive qrels
    qrels = build_extractive_qrels(queries)
    calls_made = 0

    for query in queries:
        if calls_made >= budget:
            break

        existing_ids = set(qrels.get(query.query_id, {}).keys())
        candidates = _bm25_top_k(query.text, corpus, k=top_k, exclude_ids=existing_ids)
        if not candidates:
            continue

        # Batch the LLM calls
        for i in range(0, len(candidates), batch_size):
            if calls_made >= budget:
                break
            batch = candidates[i: i + batch_size]
            tasks = [
                judge.judge(query.text, corpus[doc_id].get("text", ""))
                for doc_id in batch
                if doc_id in corpus
            ]
            grades = await asyncio.gather(*tasks, return_exceptions=True)
            calls_made += len(tasks)

            for doc_id, grade in zip(batch, grades):
                if isinstance(grade, BaseException):
                    continue
                if grade > 0:
                    qrels.setdefault(query.query_id, {})[doc_id] = int(grade)

        # Mark queries as validated
        query.validated = True
        query.metadata["label_method"] = "llm_judge_expanded"
        query.metadata["judge_model"] = getattr(judge, "model", None)

    return qrels
