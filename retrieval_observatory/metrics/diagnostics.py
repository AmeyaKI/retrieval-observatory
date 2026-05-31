from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Set

from retrieval_observatory.metrics.ranking import dedupe_preserve_rank
from retrieval_observatory.types import PipelineResult


def build_query_diagnostics(
    run_id: str,
    results: List[PipelineResult],
    qrels: Dict,
) -> List[Dict]:
    """Create per-query, per-pipeline diagnostic labels from stored stage outputs."""
    by_query: Dict[str, List[PipelineResult]] = defaultdict(list)
    for result in results:
        by_query[result.query_id].append(result)

    recall_by_query: Dict[str, List[float]] = defaultdict(list)
    final_sets: Dict[tuple, Set[str]] = {}
    first_sets: Dict[tuple, Set[str]] = {}

    for result in results:
        relevant = _relevant_set(qrels.get(result.query_id))
        if not relevant or result.status != "OK" or not result.snapshots:
            recall_by_query[result.query_id].append(0.0)
            continue
        first = set(d.id for d in result.snapshots[0].documents)
        final = set(d.id for d in result.snapshots[-1].documents)
        first_sets[(result.query_id, result.pipeline_id)] = first
        final_sets[(result.query_id, result.pipeline_id)] = final
        recall_by_query[result.query_id].append(len(final & relevant) / len(relevant))

    buckets = {
        query_id: _difficulty_bucket(scores)
        for query_id, scores in recall_by_query.items()
    }

    rows: List[Dict] = []
    for result in results:
        relevant = _relevant_set(qrels.get(result.query_id))
        stage_hits = {}
        labels = []
        if result.status != "OK":
            labels.append("unstable")

        for snap in result.snapshots:
            ids = set(dedupe_preserve_rank([d.id for d in snap.documents]))
            stage_hits[str(snap.stage_index)] = sorted(ids & relevant)

        final_ids = final_sets.get((result.query_id, result.pipeline_id), set())
        first_ids = first_sets.get((result.query_id, result.pipeline_id), set())
        missing = sorted(relevant - final_ids)

        if relevant and not first_ids & relevant:
            labels.append("candidate_miss")
        if len(result.snapshots) > 1 and first_ids & relevant and not final_ids & relevant:
            labels.append("reranker_drop")
        any_stage_hit = any(row_hits for row_hits in stage_hits.values())
        if relevant and not any_stage_hit and not any(final_sets.get((result.query_id, pid), set()) & relevant for pid in _pipeline_ids(by_query[result.query_id])):
            labels.append("id_or_qrel_issue")

        # Cross-pipeline lexical/semantic hints use adapter names as a lightweight signal.
        if result.pipeline_id.lower().find("bm25") >= 0 and not final_ids & relevant:
            if any("dense" in pid.lower() and final_sets.get((result.query_id, pid), set()) & relevant for pid in _pipeline_ids(by_query[result.query_id])):
                labels.append("lexical_mismatch")
        if "dense" in result.pipeline_id.lower() and not final_ids & relevant:
            if any("bm25" in pid.lower() and final_sets.get((result.query_id, pid), set()) & relevant for pid in _pipeline_ids(by_query[result.query_id])):
                labels.append("semantic_mismatch")

        bucket = buckets.get(result.query_id, "unknown")
        if bucket == "unstable" and "unstable" not in labels:
            labels.append("unstable")

        rows.append(
            {
                "run_id": run_id,
                "query_id": result.query_id,
                "pipeline_id": result.pipeline_id,
                "difficulty_bucket": bucket,
                "failure_labels": sorted(set(labels)),
                "missing_relevant_ids": missing,
                "stage_hits": stage_hits,
            }
        )
    return rows


def aggregate_diagnostics(rows: List[Dict]) -> Dict:
    by_bucket: Dict[str, int] = defaultdict(int)
    by_label: Dict[str, int] = defaultdict(int)
    by_pipeline: Dict[str, Dict] = {}

    for row in rows:
        by_bucket[row["difficulty_bucket"]] += 1
        pid = row.get("pipeline_id", "unknown")
        if pid not in by_pipeline:
            by_pipeline[pid] = {"n": 0, "labels": defaultdict(int), "difficulty_buckets": defaultdict(int)}
        by_pipeline[pid]["n"] += 1
        by_pipeline[pid]["difficulty_buckets"][row["difficulty_bucket"]] += 1
        for label in row.get("failure_labels", []):
            by_label[label] += 1
            by_pipeline[pid]["labels"][label] += 1

    return {
        "difficulty_buckets": dict(by_bucket),
        "failure_labels": dict(by_label),
        "by_pipeline": {
            pid: {
                "n": data["n"],
                "labels": dict(data["labels"]),
                "difficulty_buckets": dict(data["difficulty_buckets"]),
            }
            for pid, data in by_pipeline.items()
        },
        "n": len(rows),
    }


def _relevant_set(raw: object) -> Set[str]:
    if isinstance(raw, dict):
        return {doc_id for doc_id, grade in raw.items() if int(grade) > 0}
    return set(raw or [])


def _difficulty_bucket(scores: List[float]) -> str:
    if not scores:
        return "unknown"
    avg = mean(scores)
    spread = pstdev(scores) if len(scores) > 1 else 0.0
    if spread >= 0.25:
        return "discriminative"
    if avg >= 0.8:
        return "easy"
    if avg <= 0.2:
        return "hard"
    return "medium"


def _pipeline_ids(results: Iterable[PipelineResult]) -> List[str]:
    return [result.pipeline_id for result in results]
