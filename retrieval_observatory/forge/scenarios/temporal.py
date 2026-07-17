from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Set, Tuple

from retrieval_observatory.forge.types import CorpusScenario

# Reuse the temporal regex from classifier/features.py logic
_YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")

# Minimum Jaccard similarity for two docs to be considered topically similar
_MIN_JACCARD = 0.08

# Minimum token length to count as a content word
_MIN_TOKEN_LEN = 4


def _extract_years(text: str) -> Set[int]:
    return {int(m.group()) for m in _YEAR_RE.finditer(text)}


def _content_tokens(text: str) -> Set[str]:
    tokens = set(re.findall(r"\b[a-z]{4,}\b", text.lower()))
    stopwords = {
        "that", "this", "with", "from", "have", "been", "were", "they",
        "their", "which", "will", "when", "what", "also", "more", "than",
        "into", "after", "before", "about", "some", "other", "these",
        "those", "such", "over", "most", "then", "here", "there", "only",
        "both", "each", "many", "much", "well", "just", "very", "even",
    }
    return tokens - stopwords


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class TemporalScenarioDetector:
    """Detects pairs/groups of documents covering the same topic at different times."""

    scenario_type = "temporal"

    def __init__(self, min_jaccard: float = _MIN_JACCARD, max_scenarios: int = 50):
        self.min_jaccard = min_jaccard
        self.max_scenarios = max_scenarios

    def detect(self, corpus: Dict[str, Dict]) -> List[CorpusScenario]:
        # Build per-doc year sets and token sets
        doc_years: Dict[str, Set[int]] = {}
        doc_tokens: Dict[str, Set[str]] = {}

        for doc_id, doc in corpus.items():
            text = doc.get("text", "") + " " + doc.get("title", "")
            years = _extract_years(text)
            if years:
                doc_years[doc_id] = years
                doc_tokens[doc_id] = _content_tokens(text)

        if not doc_years:
            return []

        # Find pairs with overlapping vocabulary but different year anchors
        doc_ids = list(doc_years.keys())
        scenarios: List[CorpusScenario] = []
        seen_pairs: Set[Tuple[str, str]] = set()

        for i, id_a in enumerate(doc_ids):
            for id_b in doc_ids[i + 1:]:
                years_a = doc_years[id_a]
                years_b = doc_years[id_b]

                # Must span different years
                if years_a == years_b:
                    continue
                if not (years_a - years_b) and not (years_b - years_a):
                    continue

                # Must share topical vocabulary
                sim = _jaccard(doc_tokens[id_a], doc_tokens[id_b])
                if sim < self.min_jaccard:
                    continue

                pair_key = (min(id_a, id_b), max(id_a, id_b))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                year_a = min(years_a)
                year_b = min(years_b)
                if year_a <= year_b:
                    earlier, later = (id_a, year_a), (id_b, year_b)
                else:
                    earlier, later = (id_b, year_b), (id_a, year_a)

                # Content-derived id (not random): regenerating the same corpus produces the
                # same scenario_id for the same doc pair, so Test Sets datasets/query ids stay
                # stable across regenerations instead of aliasing under a fresh uuid each time.
                pair_digest = hashlib.sha256(f"{pair_key[0]}|{pair_key[1]}".encode("utf-8")).hexdigest()[:8]
                scenario = CorpusScenario(
                    scenario_id=f"temporal_{pair_digest}",
                    scenario_type="temporal",
                    anchor_doc_ids=[earlier[0], later[0]],
                    evidence_summary=(
                        f"Documents cover the same topic across different time periods "
                        f"({earlier[1]} vs {later[1]}). "
                        f"Vocabulary overlap (Jaccard={sim:.2f}) suggests shared topic; "
                        f"temporal divergence creates retrieval confusion risk."
                    ),
                    metadata={
                        "year_a": earlier[1],
                        "year_b": later[1],
                        "jaccard_similarity": round(sim, 3),
                    },
                )
                scenarios.append(scenario)

                if len(scenarios) >= self.max_scenarios:
                    return scenarios

        return scenarios
