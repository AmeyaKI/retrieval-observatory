from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# The PipelineGraph render contract — the single canonical shape the dashboard DAG view,
# the offline HTML diagram, and the MCP `get_pipeline_diagram` tool all consume. It is a
# render-only PROJECTION over stored metrics; it is never the metric storage key. Every
# quality metric value either carries its bootstrap CI or is null — no bare means cross this
# boundary (priority-1 accuracy guardrail). See pipeline_graph.schema.json for the frozen
# JSON schema both the Python producer and the TypeScript consumer validate against.

# Operator taxonomy shared with tracing.model_v2.OperatorType.
OP_TYPES = ("SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE", "TRANSFORM")


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
class PipelineGraphNode:
    node_id: str
    label: str
    op_type: str
    depth: int
    branch_id: Optional[str]  # metric-identity key within a depth layer (None = spine)
    candidate_count: float
    metrics: GraphNodeMetrics
    is_merge: bool = False
    source: str = "measured"  # always "measured"; the contract has no inferred tier

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
        }


@dataclass
class PipelineGraphEdge:
    source: str
    target: str
    kind: str = "flow"  # "flow" | "fan_in"

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target, "kind": self.kind}


@dataclass
class PipelineGraph:
    pipeline_id: str
    nodes: List[PipelineGraphNode] = field(default_factory=list)
    edges: List[PipelineGraphEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
