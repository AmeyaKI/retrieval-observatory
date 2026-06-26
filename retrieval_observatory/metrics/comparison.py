from __future__ import annotations

from typing import Dict, List, Optional, Tuple


MetricKey = Tuple[str, int, str, int, Optional[str]]


def pipeline_pairs(pipeline_ids: List[str]) -> List[Tuple[str, str]]:
    """Return (before, after) pairs for adjacent pipeline stages.

    A pipeline ID with __ separators (e.g. "bm25__rerank") is treated as a
    multi-stage pipeline. If its prefix ("bm25") also exists in pipeline_ids,
    the two form a pair. This is used to measure what each added stage contributed.

    Examples:
        ["bm25", "bm25__rerank"] -> [("bm25", "bm25__rerank")]
        ["bm25", "bm25__rerank", "bm25__rerank__cohere"] ->
            [("bm25", "bm25__rerank"), ("bm25__rerank", "bm25__rerank__cohere")]
    """
    id_set = set(pipeline_ids)
    pairs: List[Tuple[str, str]] = []
    for pid in pipeline_ids:
        parts = pid.split("__")
        if len(parts) > 1:
            prefix = "__".join(parts[:-1])
            if prefix in id_set:
                pairs.append((prefix, pid))
    return pairs


def paired_scores_by_query(metrics_a: List[Dict], metrics_b: List[Dict], metric_key: str) -> tuple[list[float], list[float], int]:
    """Return score arrays joined by query_id for a rendered metric key.

    metric_key format matches aggregate keys: pipeline|stageN|metric@k.
    """
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(metric_key)
    a = _scores_for(metrics_a, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
    b = _scores_for(metrics_b, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
    query_ids = sorted(set(a) & set(b))
    return [a[qid] for qid in query_ids], [b[qid] for qid in query_ids], len(query_ids)


def parse_metric_key(key: str) -> MetricKey:
    parts = key.split("|")
    if len(parts) < 3:
        raise ValueError(f"Invalid metric key: {key}")
    pipeline_id, stage_part, metric_part = parts[:3]
    stage_index = int(stage_part.removeprefix("stage"))
    metric_name, k_text = metric_part.rsplit("@", 1)
    branch_id = None
    if len(parts) >= 4 and parts[3].startswith("branch="):
        branch_id = parts[3].split("=", 1)[1]
    return pipeline_id, stage_index, metric_name, int(k_text), branch_id


def _scores_for(
    metrics: List[Dict],
    pipeline_id: str,
    stage_index: int,
    metric_name: str,
    k: int,
    branch_id: Optional[str] = None,
) -> Dict[str, float]:
    return {
        row["query_id"]: row["value"]
        for row in metrics
        if row["pipeline_id"] == pipeline_id
        and row["stage_index"] == stage_index
        and row["metric_name"] == metric_name
        and row["k"] == k
        and row.get("branch_id") == branch_id
    }
