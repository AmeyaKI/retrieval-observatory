from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# The PipelineGraph render contract — the single canonical shape the dashboard DAG view,
# the offline HTML diagram, and the MCP `get_pipeline_diagram` tool all consume. It is a
# render-only PROJECTION over stored metrics; it is never the metric storage key. Every
# quality metric value either carries its bootstrap CI or is null — no bare means cross this
# boundary (priority-1 accuracy guardrail). See pipeline_graph.schema.json for the frozen
# JSON schema both the Python producer and the TypeScript consumer validate against.

# Operator taxonomy shared with tracing.model.OperatorType.
OP_TYPES = ("SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE", "TRANSFORM", "GENERATE")


@dataclass
class GraphMetricValue:
    """A single scalar metric with its bootstrap CI (or nulls when unavailable)."""
    mean: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    k: Optional[int] = None  # only set for recall@k

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"mean": self.mean, "ci_low": self.ci_low, "ci_high": self.ci_high}
        if self.k is not None:
            out["k"] = self.k
        return out


@dataclass
class GraphNodeMetrics:
    ndcg10: Optional[GraphMetricValue] = None
    recall: Optional[GraphMetricValue] = None
    latency_p50: Optional[GraphMetricValue] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ndcg@10": self.ndcg10.to_dict() if self.ndcg10 else None,
            "recall": self.recall.to_dict() if self.recall else None,
            "latency_p50": self.latency_p50.to_dict() if self.latency_p50 else None,
        }


@dataclass
class GraphLatencyStats:
    count: int = 0
    mean_ms: Optional[float] = None
    p50_ms: Optional[float] = None
    p95_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "mean_ms": self.mean_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
        }


@dataclass
class PipelineGraphNode:
    node_id: str
    label: str
    op_type: str
    depth: int
    branch_id: Optional[str]  # metric-identity key within a depth layer (None = spine)
    candidate_count: float
    metrics: GraphNodeMetrics
    is_merge: bool = False
    source: str = "measured"
    input_candidate_count: float = 0.0
    parent_candidate_counts: Dict[str, float] = field(default_factory=dict)
    observed_count: int = 0
    trace_coverage: float = 0.0
    fire_rate: float = 0.0
    status_counts: Dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    latency: GraphLatencyStats = field(default_factory=GraphLatencyStats)
    is_final_output: bool = False
    final_output_count: int = 0
    configured: Optional[bool] = None
    availability: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "op_type": self.op_type,
            "depth": self.depth,
            "branch_id": self.branch_id,
            "candidate_count": self.candidate_count,
            "metrics": self.metrics.to_dict(),
            "is_merge": self.is_merge,
            "source": self.source,
            "input_candidate_count": self.input_candidate_count,
            "parent_candidate_counts": dict(self.parent_candidate_counts),
            "observed_count": self.observed_count,
            "trace_coverage": self.trace_coverage,
            "fire_rate": self.fire_rate,
            "status_counts": dict(self.status_counts),
            "cache_hits": self.cache_hits,
            "latency": self.latency.to_dict(),
            "is_final_output": self.is_final_output,
            "final_output_count": self.final_output_count,
            "configured": self.configured,
            "availability": dict(self.availability),
        }


@dataclass
class PipelineGraphEdge:
    source: str
    target: str
    kind: str = "flow"  # "flow" | "fan_in"
    observed_count: int = 0
    trace_coverage: float = 0.0
    conditional: bool = False
    source_evidence: str = "measured"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "observed_count": self.observed_count,
            "trace_coverage": self.trace_coverage,
            "conditional": self.conditional,
            "source_evidence": self.source_evidence,
        }


@dataclass
class PipelineGraph:
    pipeline_id: str
    nodes: List[PipelineGraphNode] = field(default_factory=list)
    edges: List[PipelineGraphEdge] = field(default_factory=list)
    contract_version: int = 2
    projection_mode: str = "run_union"
    trace_count: int = 0
    complete_trace_count: int = 0
    status_counts: Dict[str, int] = field(default_factory=dict)
    final_output_ids: List[str] = field(default_factory=list)
    timing_semantics: Dict[str, str] = field(default_factory=lambda: {
        "total_latency_ms": "wall_clock_ms",
        "critical_path_ms": "longest_observed_parent_path",
        "operator_sum_ms": "sum_of_observed_operator_durations",
    })
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "contract_version": self.contract_version,
            "projection_mode": self.projection_mode,
            "trace_count": self.trace_count,
            "complete_trace_count": self.complete_trace_count,
            "status_counts": dict(self.status_counts),
            "final_output_ids": list(self.final_output_ids),
            "timing_semantics": dict(self.timing_semantics),
            "warnings": list(self.warnings),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
