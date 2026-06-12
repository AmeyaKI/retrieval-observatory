from __future__ import annotations

from typing import List

from retrieval_observatory.classifier.features import extract_features
from retrieval_observatory.metrics.diagnostics import (
    compute_candidate_lineage,
    compute_churn_rate,
)
from retrieval_observatory.tracing.types import RetrievalTrace

# Proxy-failure thresholds. These are label-free signals — production has no qrels, so
# we never claim "measured" failure, only "suspected".
_LOW_CONFIDENCE_SCORE = 0.0   # top candidate score floor (overridable per service)
_HIGH_CHURN_RATE = 0.7        # fraction of candidates dropped between stages
_DEFAULT_LATENCY_BUDGET_MS = 2000.0


def predict_difficulty(query_text: str) -> str:
    """Heuristic difficulty from query-text features (no trained model required).

    Mirrors the Forge difficulty heuristic so offline and online difficulty agree.
    """
    f = extract_features(query_text)
    score = 0
    if f.get("token_count", 0) > 15:
        score += 1
    if f.get("has_temporal_anchor", 0) >= 1.0:
        score += 1
    if f.get("has_negation", 0) >= 1.0:
        score += 1
    if f.get("has_comparison", 0) >= 1.0:
        score += 1
    if f.get("multi_clause", 0) >= 1.0:
        score += 1
    if score <= 1:
        return "easy"
    if score == 2:
        return "medium"
    if score == 3:
        return "hard"
    return "extreme"


def detect_suspected_failures(
    trace: RetrievalTrace,
    latency_budget_ms: float = _DEFAULT_LATENCY_BUDGET_MS,
    low_confidence_score: float = _LOW_CONFIDENCE_SCORE,
) -> List[str]:
    """Compute label-free proxy failure signals for a trace.

    Each label names a concrete, observable condition — never a measured-Recall claim.
    """
    labels: List[str] = []
    final = trace.final_results or (trace.snapshots[-1].documents if trace.snapshots else [])

    # 1. empty / near-empty candidate set
    if len(final) == 0:
        labels.append("empty_candidates")

    # 2. low retrieval confidence (top score at/below floor)
    if final:
        top_score = max((d.score for d in final), default=0.0)
        if top_score <= low_confidence_score:
            labels.append("low_confidence")

    # 3. high inter-stage churn / late-stage drop (reuse offline lineage machinery)
    if len(trace.snapshots) >= 2:
        lineages = compute_candidate_lineage(trace.as_pipeline_result())
        churn = compute_churn_rate(lineages)
        if churn >= _HIGH_CHURN_RATE:
            labels.append("high_churn")

    # 4. latency over budget
    if trace.total_latency_ms > latency_budget_ms:
        labels.append("latency_over_budget")

    return labels


def enrich(
    trace: RetrievalTrace,
    latency_budget_ms: float = _DEFAULT_LATENCY_BUDGET_MS,
    low_confidence_score: float = _LOW_CONFIDENCE_SCORE,
) -> RetrievalTrace:
    """Populate predicted_difficulty + suspected_failures in place and return the trace."""
    if trace.predicted_difficulty is None:
        trace.predicted_difficulty = predict_difficulty(trace.query_text)
    trace.suspected_failures = detect_suspected_failures(
        trace, latency_budget_ms=latency_budget_ms, low_confidence_score=low_confidence_score
    )
    return trace
