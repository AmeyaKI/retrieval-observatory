from __future__ import annotations

from typing import List, Optional

from retrieval_observatory.classifier.features import extract_features
from retrieval_observatory.tracing.model import RetrievalTrace

# Proxy-failure thresholds. These are label-free signals — production has no qrels, so
# we never claim "measured" failure, only "suspected".
# Pipelines that return unscored docs (all scores 0.0) are treated as unscored, not low-confidence.
_LOW_CONFIDENCE_SCORE: float = 0.05  # top candidate score floor when scores are present
_HIGH_CHURN_RATE = 0.7        # fraction of candidates dropped between stages
_DEFAULT_LATENCY_BUDGET_MS = 2000.0


def predict_difficulty(query_text: str) -> str:
    """Heuristic difficulty from query-text features (no trained model required).

    Mirrors the Test Sets difficulty heuristic so offline and online difficulty agree.
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
    low_confidence_score: Optional[float] = _LOW_CONFIDENCE_SCORE,
) -> List[str]:
    """Compute label-free proxy failure signals for a trace.

    Each label names a concrete, observable condition — never a measured-Recall claim.
    """
    labels: List[str] = []
    final_ids = set(trace.final_op_ids)
    final_spans = [span for span in trace.spans if span.op_id in final_ids]
    final = [candidate for span in final_spans for candidate in span.outputs]

    # 1. empty / near-empty candidate set
    if len(final) == 0:
        labels.append("empty_candidates")

    # 2. low retrieval confidence (top score at/below floor) when scores are present.
    if final and low_confidence_score is not None:
        scores = [d.score for d in final]
        all_unscored = all(s == 0.0 for s in scores)
        if not all_unscored:
            top_score = max(scores, default=0.0)
            if top_score <= low_confidence_score:
                labels.append("low_confidence")

    # 3. high inter-stage churn / late-stage drop (reuse offline lineage machinery)
    fired = [span for span in trace.spans if span.status == "FIRED"]
    if len(fired) >= 2:
        previous = {candidate.doc_id for candidate in fired[-2].outputs}
        current = {candidate.doc_id for candidate in fired[-1].outputs}
        churn = len(previous - current) / len(previous) if previous else 0.0
        if churn >= _HIGH_CHURN_RATE:
            labels.append("high_churn")

    # 4. latency over budget
    if trace.timing.wall_clock_ms > latency_budget_ms:
        labels.append("latency_over_budget")

    return labels


def enrich(
    trace: RetrievalTrace,
    latency_budget_ms: float = _DEFAULT_LATENCY_BUDGET_MS,
    low_confidence_score: Optional[float] = _LOW_CONFIDENCE_SCORE,
) -> RetrievalTrace:
    """Populate predicted_difficulty + suspected_failures in place and return the trace."""
    metadata = dict(trace.metadata)
    metadata.setdefault("predicted_difficulty", predict_difficulty(trace.query_text))
    metadata["suspected_failures"] = detect_suspected_failures(
        trace, latency_budget_ms=latency_budget_ms, low_confidence_score=low_confidence_score
    )
    trace.metadata = metadata
    return trace
