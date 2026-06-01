from __future__ import annotations

from typing import Any, Dict, List, Union


def pipeline_cost_per_1k(
    config: Union[Dict[str, Any], Any],
    pipeline_id: str,
    costs: Dict[str, Dict[str, float]] | None = None,
) -> float:
    """Sum configured per_1k_queries for each stage in a pipeline."""
    if costs is None:
        if hasattr(config, "costs"):
            costs = config.costs
        elif isinstance(config, dict):
            costs = config.get("costs", {})
        else:
            costs = {}

    pipelines: List[Dict[str, Any]]
    if hasattr(config, "pipelines"):
        pipelines = [p.model_dump() if hasattr(p, "model_dump") else p for p in config.pipelines]
    elif isinstance(config, dict):
        pipelines = config.get("pipelines", [])
    else:
        pipelines = []

    pipeline = next((p for p in pipelines if p.get("id") == pipeline_id), None)
    if not pipeline:
        return 0.0

    total = 0.0
    for stage in pipeline.get("stages", []):
        if hasattr(stage, "model_dump"):
            stage = stage.model_dump()
        stage_id = stage.get("retriever_id") or stage.get("type")
        stage_cost = costs.get(stage_id, costs.get(stage.get("type"), {}))
        total += float(stage_cost.get("per_1k_queries", 0.0))
    return total
