"""Rule-based query templates (no LLM) for Forge stress-test generation."""
from __future__ import annotations

import hashlib
from typing import Dict, List

from retrieval_observatory.forge.types import CorpusScenario, SyntheticQuery

_COMPARISON_TEMPLATES = [
    "How does {topic} compare to alternatives?",
    "What is the difference between {topic} and other approaches?",
    "{topic} vs other methods — which is better?",
]

_CONSTRAINT_TEMPLATES = [
    "What are the requirements and constraints for {topic}?",
    "List mandatory steps when implementing {topic}.",
    "What must I include when configuring {topic}?",
]

_LONG_TAIL_TEMPLATES = [
    "In what edge cases does {topic} fail or behave unexpectedly during production deployments with strict latency budgets?",
    "Explain the nuanced tradeoffs when tuning {topic} for multilingual corpora with sparse metadata.",
]


def _topic_from_doc(corpus: Dict[str, Dict], doc_id: str) -> str:
    doc = corpus.get(doc_id, {})
    title = doc.get("title") or doc.get("text", "")[:60]
    return title.strip().lower() or "this configuration"


def generate_rule_based_queries(
    scenario: CorpusScenario,
    corpus: Dict[str, Dict],
    query_types: List[str],
    n_per_type: int = 2,
) -> List[SyntheticQuery]:
    """Generate deterministic queries for comparison, constraint, and long_tail types."""
    queries: List[SyntheticQuery] = []
    anchor_ids = list(scenario.anchor_doc_ids)
    if not anchor_ids:
        return queries
    topic = _topic_from_doc(corpus, anchor_ids[0])

    templates_map = {
        "comparison": _COMPARISON_TEMPLATES,
        "constraint": _CONSTRAINT_TEMPLATES,
        "long_tail": _LONG_TAIL_TEMPLATES,
    }

    for qtype in query_types:
        templates = templates_map.get(qtype)
        if not templates:
            continue
        for i, tmpl in enumerate(templates[:n_per_type]):
            # Content-derived id: scenario_id + qtype + template index is deterministic,
            # so regenerating the same scenario reproduces the same query_id instead of a
            # fresh random one each time.
            digest = hashlib.sha256(f"{scenario.scenario_id}|{qtype}|{i}".encode("utf-8")).hexdigest()[:10]
            queries.append(
                SyntheticQuery(
                    query_id=f"forge_{qtype}_{digest}",
                    text=tmpl.format(topic=topic),
                    scenario_id=scenario.scenario_id,
                    query_type=qtype,
                    positive_doc_ids=anchor_ids[:1],
                    difficulty_label="hard" if qtype == "long_tail" else "medium",
                    failure_category=f"{qtype}_stress" if qtype != "comparison" else None,
                )
            )
    return queries
