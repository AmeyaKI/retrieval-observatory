from __future__ import annotations

from typing import List, Optional

from retrieval_observatory.classifier.features import extract_features
from retrieval_observatory.forge.types import SyntheticQuery


def _heuristic_score(query: SyntheticQuery) -> int:
    """Score query difficulty based on text features and query type."""
    features = extract_features(query.text)
    score = 0

    if features.get("token_count", 0) > 15:
        score += 1
    if features.get("has_temporal_anchor", 0) > 0:
        score += 1
    if features.get("has_negation", 0) > 0:
        score += 1
    if features.get("has_comparison", 0) > 0:
        score += 1
    if query.query_type == "adversarial":
        score += 2
    elif query.query_type == "temporal":
        score += 1

    return score


def _score_to_label(score: int) -> str:
    if score <= 1:
        return "easy"
    if score == 2:
        return "medium"
    if score == 3:
        return "hard"
    return "extreme"


def assign_difficulty_labels(
    queries: List[SyntheticQuery],
    model_path: Optional[str] = None,
) -> None:
    """Assign difficulty labels to queries in-place.

    Uses the trained QueryDifficultyModel if a model_path is provided and the
    model exists; falls back to rule-based heuristics otherwise.
    """
    if model_path:
        try:
            from retrieval_observatory.classifier.model import load_model
            model = load_model(model_path)
            for query in queries:
                result = model.predict(query.text)
                label = result.get("label", "medium")
                # Map classifier labels to forge difficulty labels
                label_map = {"easy": "easy", "medium": "medium", "hard": "hard"}
                query.difficulty_label = label_map.get(label, "medium")
            return
        except (FileNotFoundError, ImportError):
            pass  # Fall through to heuristics

    for query in queries:
        score = _heuristic_score(query)
        query.difficulty_label = _score_to_label(score)
