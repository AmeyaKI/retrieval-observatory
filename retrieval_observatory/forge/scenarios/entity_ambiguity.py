"""Heuristic entity-ambiguity scenario detection."""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Dict, List

from retrieval_observatory.forge.types import CorpusScenario

_AMBIGUITY_PATTERNS = [
    re.compile(r"\b([A-Z][a-z]+)\b.*\b(same|also known|formerly|now called)\b", re.I),
]


class EntityAmbiguityDetector:
    """Detect docs that share ambiguous entity tokens (heuristic)."""

    scenario_type = "entity_ambiguity"

    def __init__(self, max_scenarios: int = 20):
        self.max_scenarios = max_scenarios

    def detect(self, corpus: Dict[str, Dict]) -> List[CorpusScenario]:
        token_docs: Dict[str, List[str]] = defaultdict(list)
        for doc_id, doc in corpus.items():
            text = f"{doc.get('title', '')} {doc.get('text', '')}"
            for pat in _AMBIGUITY_PATTERNS:
                for m in pat.finditer(text):
                    token = m.group(1).lower()
                    token_docs[token].append(doc_id)

        scenarios: List[CorpusScenario] = []
        for token, doc_ids in token_docs.items():
            unique = list(dict.fromkeys(doc_ids))
            if len(unique) < 2:
                continue
            scenarios.append(
                CorpusScenario(
                    scenario_id=f"entity-{token}-{uuid.uuid4().hex[:6]}",
                    scenario_type=self.scenario_type,
                    anchor_doc_ids=unique[:3],
                    evidence_summary=f"Ambiguous entity token '{token}' appears across {len(unique)} documents",
                    metadata={"token": token},
                )
            )
            if len(scenarios) >= self.max_scenarios:
                break
        return scenarios
