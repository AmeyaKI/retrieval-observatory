from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Dict, List, Set

from retrieval_observatory.types import CandidateLineage


def compute_candidate_lineage(result: Any) -> List[CandidateLineage]:
    """Legacy-shaped flow statistics only; causal diagnosis lives in diagnostics/."""
    lineages: List[CandidateLineage] = []
    previous: Set[str] = set()
    for snapshot in result.snapshots:
        current = {document.id for document in snapshot.documents}
        expansion = bool(previous) and len(current) > len(previous)
        lineages.append(CandidateLineage(
            stage_index=snapshot.stage_index,
            stage_id=snapshot.stage_id,
            entered=sorted(current - previous),
            survived=sorted(current & previous),
            dropped=sorted(previous - current),
            churn_rate=0.0 if not previous or expansion else len(previous - current) / len(previous),
            is_expansion=expansion,
        ))
        previous = current
    return lineages


def compute_churn_rate(lineages: List[CandidateLineage]) -> float:
    narrowing = [item.churn_rate for item in lineages if item.stage_index > 0 and not item.is_expansion]
    return mean(narrowing) if narrowing else 0.0


def aggregate_diagnostics(rows: List[Dict]) -> Dict:
    by_bucket: Dict[str, int] = defaultdict(int)
    by_label: Dict[str, int] = defaultdict(int)
    by_pipeline: Dict[str, Dict] = {}
    for row in rows:
        bucket = row.get("difficulty_bucket", "unknown")
        by_bucket[bucket] += 1
        pipeline_id = row.get("pipeline_id", "unknown")
        data = by_pipeline.setdefault(pipeline_id, {"n": 0, "labels": defaultdict(int), "difficulty_buckets": defaultdict(int)})
        data["n"] += 1
        data["difficulty_buckets"][bucket] += 1
        for label in row.get("failure_labels", []):
            by_label[label] += 1
            data["labels"][label] += 1
    return {
        "difficulty_buckets": dict(by_bucket),
        "failure_labels": dict(by_label),
        "by_pipeline": {key: {"n": value["n"], "labels": dict(value["labels"]), "difficulty_buckets": dict(value["difficulty_buckets"])} for key, value in by_pipeline.items()},
        "n": len(rows),
    }


def predict_retrieval_risks(query_text: str) -> List[str]:
    from retrieval_observatory.classifier.features import extract_features
    from retrieval_observatory.tracing.enrich import predict_difficulty

    features = extract_features(query_text)
    risks: List[str] = []
    if predict_difficulty(query_text) in ("hard", "extreme"):
        risks.append("high_difficulty_query")
    if features.get("has_temporal_anchor", 0) >= 1.0:
        risks.append("temporal_sensitivity")
    if features.get("has_comparison", 0) >= 1.0:
        risks.append("comparison_query")
    if features.get("token_count", 0) > 20:
        risks.append("long_query_may_need_higher_k")
    if features.get("has_negation", 0) >= 1.0:
        risks.append("negation_may_hurt_lexical_match")
    return risks
