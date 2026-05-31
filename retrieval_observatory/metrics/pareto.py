from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


@dataclass
class ParetoPipelineInput:
    pipeline_id: str
    stage_index: int
    ndcg10: float
    recall10: float
    latency_p50: float
    latency_p95: float
    cost_per_1k: Optional[float] = None


@dataclass
class ParetoPipelineResult:
    pipeline_id: str
    stage_index: int
    metrics: Dict[str, Optional[float]]
    is_pareto_optimal: bool
    dominated_by: List[str]


@dataclass
class ParetoResult:
    objectives: List[str]
    cost_included: bool
    cost_excluded_reason: Optional[str]
    pipelines: List[ParetoPipelineResult]
    frontier_order: List[str]


_BASE_OBJECTIVES = ["ndcg@10", "recall@10", "latency_p50", "latency_p95"]


def compute_pareto_frontier(pipelines: List[ParetoPipelineInput]) -> ParetoResult:
    """Return Pareto-optimal pipelines and dominators using vectorized NumPy."""
    if not pipelines:
        return ParetoResult(
            objectives=[],
            cost_included=False,
            cost_excluded_reason=None,
            pipelines=[],
            frontier_order=[],
        )

    cost_values = [p.cost_per_1k for p in pipelines]
    cost_included = all(c is not None and c > 0 for c in cost_values)
    cost_excluded_reason: Optional[str] = None

    if cost_included:
        objectives = _BASE_OBJECTIVES + ["cost_per_1k"]
    else:
        objectives = list(_BASE_OBJECTIVES)
        missing = [p.pipeline_id for p in pipelines if p.cost_per_1k is None or p.cost_per_1k <= 0]
        if any(c is not None and c > 0 for c in cost_values):
            cost_excluded_reason = (
                f"Cost configuration missing for pipeline(s): {', '.join(missing)}"
            )
        else:
            cost_excluded_reason = "No cost configuration present in experiment config"

    obj_matrix = _objective_matrix(pipelines, objectives)
    maximize_mask = np.array([obj in {"ndcg@10", "recall@10"} for obj in objectives])

    # dominates[j, i] — pipeline j dominates pipeline i
    better = np.where(
        maximize_mask,
        obj_matrix[:, None, :] >= obj_matrix[None, :, :],
        obj_matrix[:, None, :] <= obj_matrix[None, :, :],
    )
    strict = np.where(
        maximize_mask,
        obj_matrix[:, None, :] > obj_matrix[None, :, :],
        obj_matrix[:, None, :] < obj_matrix[None, :, :],
    )
    dominates = better.all(axis=2) & strict.any(axis=2)
    np.fill_diagonal(dominates, False)

    pipeline_ids = [p.pipeline_id for p in pipelines]
    results: List[ParetoPipelineResult] = []
    frontier_ids: List[str] = []

    for i, pipeline in enumerate(pipelines):
        dominators = [pipeline_ids[j] for j in range(len(pipelines)) if dominates[j, i]]
        is_optimal = not dominators
        if is_optimal:
            frontier_ids.append(pipeline.pipeline_id)

        results.append(
            ParetoPipelineResult(
                pipeline_id=pipeline.pipeline_id,
                stage_index=pipeline.stage_index,
                metrics={
                    "ndcg@10": pipeline.ndcg10,
                    "recall@10": pipeline.recall10,
                    "latency_p50": pipeline.latency_p50,
                    "latency_p95": pipeline.latency_p95,
                    "cost_per_1k": pipeline.cost_per_1k if cost_included else None,
                },
                is_pareto_optimal=is_optimal,
                dominated_by=dominators,
            )
        )

    latency_by_id = {p.pipeline_id: p.latency_p50 for p in pipelines}
    frontier_order = sorted(frontier_ids, key=lambda pid: latency_by_id[pid])

    return ParetoResult(
        objectives=objectives,
        cost_included=cost_included,
        cost_excluded_reason=cost_excluded_reason if not cost_included else None,
        pipelines=results,
        frontier_order=frontier_order,
    )


def _objective_matrix(pipelines: List[ParetoPipelineInput], objectives: List[str]) -> np.ndarray:
    rows = []
    for pipeline in pipelines:
        row = []
        for objective in objectives:
            if objective == "ndcg@10":
                row.append(pipeline.ndcg10)
            elif objective == "recall@10":
                row.append(pipeline.recall10)
            elif objective == "latency_p50":
                row.append(pipeline.latency_p50)
            elif objective == "latency_p95":
                row.append(pipeline.latency_p95)
            elif objective == "cost_per_1k":
                row.append(pipeline.cost_per_1k)
            else:
                raise ValueError(f"Unknown objective: {objective}")
        rows.append(row)
    return np.array(rows, dtype=float)
