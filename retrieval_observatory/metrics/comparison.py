from __future__ import annotations

from typing import Dict, List, Tuple


MetricKey = Tuple[str, int, str, int]


def paired_scores_by_query(metrics_a: List[Dict], metrics_b: List[Dict], metric_key: str) -> tuple[list[float], list[float], int]:
    """Return score arrays joined by query_id for a rendered metric key.

    metric_key format matches aggregate keys: pipeline|stageN|metric@k.
    """
    pipeline_id, stage_index, metric_name, k = parse_metric_key(metric_key)
    a = _scores_for(metrics_a, pipeline_id, stage_index, metric_name, k)
    b = _scores_for(metrics_b, pipeline_id, stage_index, metric_name, k)
    query_ids = sorted(set(a) & set(b))
    return [a[qid] for qid in query_ids], [b[qid] for qid in query_ids], len(query_ids)


def parse_metric_key(key: str) -> MetricKey:
    pipeline_id, stage_part, metric_part = key.split("|", 2)
    stage_index = int(stage_part.removeprefix("stage"))
    metric_name, k_text = metric_part.rsplit("@", 1)
    return pipeline_id, stage_index, metric_name, int(k_text)


def _scores_for(metrics: List[Dict], pipeline_id: str, stage_index: int, metric_name: str, k: int) -> Dict[str, float]:
    return {
        row["query_id"]: row["value"]
        for row in metrics
        if row["pipeline_id"] == pipeline_id
        and row["stage_index"] == stage_index
        and row["metric_name"] == metric_name
        and row["k"] == k
    }
