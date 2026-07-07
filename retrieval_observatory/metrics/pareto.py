from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ParetoPipelineInput:
    pipeline_id: str
    stage_index: int
    ndcg10: float
    recall10: float
    latency_p50: float
    latency_p95: float
    cost_per_1k: Optional[float] = None
    ndcg10_ci_low: Optional[float] = None
    ndcg10_ci_high: Optional[float] = None
    recall10_ci_low: Optional[float] = None
    recall10_ci_high: Optional[float] = None


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
    """Return Pareto-optimal pipelines and dominators."""
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

    pipeline_ids = [p.pipeline_id for p in pipelines]
    results: List[ParetoPipelineResult] = []
    frontier_ids: List[str] = []

    for i, pipeline in enumerate(pipelines):
        dominators = [
            pipeline_ids[j]
            for j, candidate in enumerate(pipelines)
            if i != j and _dominates(candidate, pipeline, objectives)
        ]
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


def _dominates(left: ParetoPipelineInput, right: ParetoPipelineInput, objectives: List[str]) -> bool:
    better_or_equal = []
    strictly_better = []
    for objective in objectives:
        left_value = _objective_value(left, objective)
        right_value = _objective_value(right, objective)
        if objective in {"ndcg@10", "recall@10"}:
            better_or_equal.append(left_value >= right_value)
            strictly_better.append(_significantly_better(left, right, objective))
        else:
            better_or_equal.append(left_value <= right_value)
            strictly_better.append(left_value < right_value)
    return all(better_or_equal) and any(strictly_better)


def _significantly_better(left: ParetoPipelineInput, right: ParetoPipelineInput, objective: str) -> bool:
    """A quality objective only counts toward dominance if its bootstrap CIs don't
    overlap. Without CI data (fields left as None), falls back to the point-estimate
    comparison so existing callers that don't supply CIs are unaffected."""
    left_low, left_high = _ci_bounds(left, objective)
    right_low, right_high = _ci_bounds(right, objective)
    if left_low is None or right_low is None or left_high is None or right_high is None:
        return _objective_value(left, objective) > _objective_value(right, objective)
    return left_low > right_high


def _ci_bounds(pipeline: ParetoPipelineInput, objective: str) -> tuple[Optional[float], Optional[float]]:
    if objective == "ndcg@10":
        return pipeline.ndcg10_ci_low, pipeline.ndcg10_ci_high
    if objective == "recall@10":
        return pipeline.recall10_ci_low, pipeline.recall10_ci_high
    return None, None


def _objective_value(pipeline: ParetoPipelineInput, objective: str) -> float:
    if objective == "ndcg@10":
        return pipeline.ndcg10
    if objective == "recall@10":
        return pipeline.recall10
    if objective == "latency_p50":
        return pipeline.latency_p50
    if objective == "latency_p95":
        return pipeline.latency_p95
    if objective == "cost_per_1k":
        return float(pipeline.cost_per_1k or 0.0)
    raise ValueError(f"Unknown objective: {objective}")
