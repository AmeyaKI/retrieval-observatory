from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Tuple

from retrieval_observatory.forge.types import CorpusScenario

# Pattern: "Full Form (ABBR)" or "ABBR (Full Form)" where ABBR is 2-6 uppercase letters
_ABBR_INLINE = re.compile(
    r"\b([A-Z][a-zA-Z ]{2,40})\s*\(([A-Z]{2,6})\)"    # Full (ABBR)
    r"|([A-Z]{2,6})\s*\(([A-Z][a-zA-Z ]{2,40})\)"     # ABBR (Full)
)

# Pattern for standalone ABBR usage (2-6 uppercase letters, not at sentence start)
_ABBR_STANDALONE = re.compile(r"(?<!\.\s)\b([A-Z]{2,6})\b(?!\s*\()")


def _extract_alias_pairs(text: str) -> List[Tuple[str, str]]:
    """Return list of (full_form, abbreviation) pairs found in text."""
    pairs = []
    for m in _ABBR_INLINE.finditer(text):
        if m.group(1) and m.group(2):
            pairs.append((m.group(1).strip(), m.group(2).strip()))
        elif m.group(3) and m.group(4):
            pairs.append((m.group(4).strip(), m.group(3).strip()))
    return pairs


class AliasScenarioDetector:
    """Detects alias/abbreviation mismatch scenarios in a corpus.

    Finds cases where some documents define or use the full form of a term
    while others use only the abbreviation — a common retrieval failure mode
    where a query using the abbreviation misses documents using the full form.
    """

    scenario_type = "alias"

    def __init__(self, max_scenarios: int = 30):
        self.max_scenarios = max_scenarios

    def detect(self, corpus: Dict[str, Dict]) -> List[CorpusScenario]:
        # Map: abbreviation -> (full_form, [defining_doc_ids])
        abbr_to_full: Dict[str, Tuple[str, List[str]]] = {}
        # Map: abbreviation -> [doc_ids that use it standalone]
        abbr_standalone_docs: Dict[str, List[str]] = {}

        for doc_id, doc in corpus.items():
            text = doc.get("text", "") + " " + doc.get("title", "")

            # Extract inline alias definitions
            for full_form, abbr in _extract_alias_pairs(text):
                if abbr not in abbr_to_full:
                    abbr_to_full[abbr] = (full_form, [])
                abbr_to_full[abbr][1].append(doc_id)

            # Track standalone abbreviation usage
            for m in _ABBR_STANDALONE.finditer(text):
                abbr = m.group(1)
                if len(abbr) >= 2:
                    abbr_standalone_docs.setdefault(abbr, []).append(doc_id)

        scenarios: List[CorpusScenario] = []

        for abbr, (full_form, defining_docs) in abbr_to_full.items():
            # Find docs that use ONLY the abbreviation (not the full form)
            full_lower = full_form.lower()
            standalone_only: List[str] = []
            for doc_id in abbr_standalone_docs.get(abbr, []):
                if doc_id in defining_docs:
                    continue
                doc_text = corpus[doc_id].get("text", "").lower()
                if full_lower not in doc_text:
                    standalone_only.append(doc_id)

            if not standalone_only:
                continue

            all_docs = list(set(defining_docs + standalone_only))
            # Content-derived id: `abbr` is unique per corpus scan, so regenerating the same
            # corpus reproduces the same scenario_id instead of a fresh random one each time.
            abbr_digest = hashlib.sha256(abbr.encode("utf-8")).hexdigest()[:8]
            scenario = CorpusScenario(
                scenario_id=f"alias_{abbr_digest}",
                scenario_type="alias",
                anchor_doc_ids=all_docs[:10],  # cap at 10 docs per scenario
                evidence_summary=(
                    f"Alias mismatch: '{abbr}' abbreviates '{full_form}'. "
                    f"{len(defining_docs)} doc(s) define/use the full form; "
                    f"{len(standalone_only)} doc(s) use only the abbreviation. "
                    f"A query using one form may miss documents using the other."
                ),
                metadata={
                    "abbreviation": abbr,
                    "full_form": full_form,
                    "full_form_doc_count": len(defining_docs),
                    "abbr_only_doc_count": len(standalone_only),
                },
            )
            scenarios.append(scenario)

            if len(scenarios) >= self.max_scenarios:
                break

        return scenarios
