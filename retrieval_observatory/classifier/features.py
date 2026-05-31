from __future__ import annotations

import re
from typing import Dict, List

_WH_TYPES = ("what", "how", "when", "who", "where", "which")
_NEGATION = frozenset(
    {"not", "no", "never", "none", "nothing", "nowhere", "without", "nor", "neither"}
)
_COMPARISON = frozenset(
    {"than", "versus", "vs", "compared", "compare", "better", "worse", "more", "less", "most", "least"}
)
_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_TEMPORAL_RE = re.compile(
    r"\b(?:19|20)\d{2}\b|"
    r"\b(?:last|next|this|past|recent|since|before|after|during)\s+\w+\b|"
    r"\b(?:" + "|".join(_MONTHS) + r")\b",
    re.IGNORECASE,
)

QUESTION_TYPE_FEATURES = [f"question_type_{w}" for w in _WH_TYPES] + ["question_type_other"]

FEATURE_NAMES: List[str] = [
    "token_count",
    "char_count",
    "lexical_density",
    "has_temporal_anchor",
    "named_entity_density",
    "has_negation",
    "has_comparison",
    "multi_clause",
    *QUESTION_TYPE_FEATURES,
]


def _tokenize(text: str) -> List[str]:
    return text.split()


def _question_type_onehot(text: str) -> Dict[str, float]:
    result = {f"question_type_{w}": 0.0 for w in _WH_TYPES}
    result["question_type_other"] = 1.0
    stripped = text.strip().lower()
    for wh in _WH_TYPES:
        if stripped.startswith(wh + " ") or stripped == wh:
            result[f"question_type_{wh}"] = 1.0
            result["question_type_other"] = 0.0
            break
    return result


def _named_entity_density(tokens: List[str]) -> float:
    if not tokens:
        return 0.0
    count = 0
    for i, tok in enumerate(tokens):
        if not tok or not tok[0].isupper():
            continue
        if i == 0:
            continue
        if tokens[i - 1].endswith((".", "!", "?")):
            continue
        count += 1
    return count / len(tokens)


def extract_features(text: str) -> Dict[str, float]:
    """Extract O(n) query-text features with no model calls."""
    tokens = _tokenize(text.strip())
    token_count = len(tokens)
    char_count = len(text)
    unique = len(set(t.lower() for t in tokens)) if tokens else 0
    lexical_density = unique / max(token_count, 1)

    lower_tokens = [t.lower().strip(".,!?;:'\"") for t in tokens]
    has_negation = 1.0 if any(
        t in _NEGATION or t.endswith("n't") for t in lower_tokens
    ) else 0.0
    has_comparison = 1.0 if any(t in _COMPARISON for t in lower_tokens) else 0.0

    multi_clause = 0.0
    if ";" in text or text.count(",") >= 2:
        multi_clause = 1.0
    elif " and " in text.lower() or " or " in text.lower():
        multi_clause = 1.0

    features: Dict[str, float] = {
        "token_count": float(token_count),
        "char_count": float(char_count),
        "lexical_density": lexical_density,
        "has_temporal_anchor": 1.0 if _TEMPORAL_RE.search(text) else 0.0,
        "named_entity_density": _named_entity_density(tokens),
        "has_negation": has_negation,
        "has_comparison": has_comparison,
        "multi_clause": multi_clause,
        **_question_type_onehot(text),
    }
    return features


def features_to_vector(features: Dict[str, float]) -> List[float]:
    return [features[name] for name in FEATURE_NAMES]
