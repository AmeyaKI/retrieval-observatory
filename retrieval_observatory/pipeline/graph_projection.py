from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from retrieval_observatory.pipeline.graph_contract import (
    GraphMetricValue,
    GraphNodeMetrics,
    PipelineGraph,
    PipelineGraphEdge,
    PipelineGraphNode,
)

# Project stored metrics + persisted traces into the PipelineGraph render contract. Topology
# comes from trace `parent_ids` (the true DAG); per-node metrics are looked up by
# (pipeline_id, depth, branch_id) — the exact key compute_from_traces writes. This is exact for
# linear pipelines (one node per depth, branch_id=None → same keys compute_and_store writes) and
# for DAG pipelines (parallel nodes share a depth, each keyed by branch_id=op_id).

_OP_TYPE_LABELS = {
    "SOURCE": "Retrieval",
    "FUSE": "Fusion",
    "RERANK": "Reranking",
    "BOOST": "Boosting",
    "EXPAND": "Expansion",
    "FILTER": "Filtering",
    "GATE": "Gating",
    "TRANSFORM": "Transform",
}


def _node_label(op_name: str) -> str:
    return (
        op_name.replace("_rerank", " Reranker")
        .replace("_retriever", " Retriever")
        .replace("_", " ")
        .strip()
        .title()
    )


def _span_depths(fired_spans: list) -> Dict[str, int]:
    fired_ids = {s.op_id for s in fired_spans}
    span_by_id = {s.op_id: s for s in fired_spans}
    cache: Dict[str, int] = {}

    def depth_of(op_id: str, seen: frozenset) -> int:
        if op_id in cache:
            return cache[op_id]
        span = span_by_id[op_id]
        parents = [p for p in span.parent_ids if p in fired_ids and p not in seen]
        d = 0 if not parents else 1 + max(depth_of(p, seen | {op_id}) for p in parents)
        cache[op_id] = d
        return d

    return {s.op_id: depth_of(s.op_id, frozenset()) for s in fired_spans}


def _metric_value(entry: Optional[Dict[str, Any]], *, with_k: bool = False) -> Optional[GraphMetricValue]:
    if not entry:
        return None
    return GraphMetricValue(
        mean=entry.get("mean"),
        ci_low=entry.get("ci_low"),
        ci_high=entry.get("ci_high"),
        k=entry.get("k") if with_k else None,
    )


def build_pipeline_graphs(aggregated: Dict[str, Any], traces: list) -> List[PipelineGraph]:
    """Return one PipelineGraph per pipeline that has a persisted trace + metrics."""
    # Index aggregate entries by (pipeline_id, stage_index, metric_name, k, branch_id).
    metric_index: Dict[tuple, Dict[str, Any]] = {}
    for entry in aggregated.values():
        metric_index[(
            entry.get("pipeline_id"),
            entry.get("stage_index"),
            entry.get("metric_name"),
            entry.get("k"),
            entry.get("branch_id"),
        )] = entry

    # Group representative + candidate-count samples per pipeline.
    traces_by_pipeline: Dict[str, list] = defaultdict(list)
    for trace in traces:
        if getattr(trace, "status", "OK") == "OK":
            traces_by_pipeline[trace.pipeline_id].append(trace)

    graphs: List[PipelineGraph] = []
    for pipeline_id, pipeline_traces in sorted(traces_by_pipeline.items()):
        representative = pipeline_traces[0]
        fired = [s for s in representative.spans if s.status in ("FIRED", "SKIPPED_BY_GATE")]
        if not fired:
            continue
        depth_by_op = _span_depths(fired)
        nodes_at_depth: Dict[int, int] = defaultdict(int)
        for depth in depth_by_op.values():
            nodes_at_depth[depth] += 1

        # Mean candidate count per op across this pipeline's traces (measured).
        cand_sums: Dict[str, float] = defaultdict(float)
        cand_counts: Dict[str, int] = defaultdict(int)
        for trace in pipeline_traces:
            for span in trace.spans:
                if span.status in ("FIRED", "SKIPPED_BY_GATE"):
                    cand_sums[span.op_id] += len(span.outputs)
                    cand_counts[span.op_id] += 1

        def _best_recall(depth: int, branch_id: Optional[str]) -> Optional[GraphMetricValue]:
            recalls = [
                (k, e) for (pid, sidx, mname, k, br), e in metric_index.items()
                if pid == pipeline_id and sidx == depth and br == branch_id and mname == "recall"
            ]
            if not recalls:
                return None
            _, entry = max(recalls, key=lambda kv: kv[0] or 0)
            return _metric_value(entry, with_k=True)

        nodes: List[PipelineGraphNode] = []
        edges: List[PipelineGraphEdge] = []
        for span in fired:
            depth = depth_by_op[span.op_id]
            branch_id = None if nodes_at_depth[depth] == 1 else span.op_id
            fired_parents = [p for p in span.parent_ids if p in depth_by_op]
            metrics = GraphNodeMetrics(
                ndcg10=_metric_value(metric_index.get((pipeline_id, depth, "ndcg", 10, branch_id))),
                recall=_best_recall(depth, branch_id),
                latency_p50=_metric_value(metric_index.get((pipeline_id, depth, "latency_p50", 0, branch_id))),
            )
            candidate_count = cand_sums[span.op_id] / cand_counts[span.op_id] if cand_counts[span.op_id] else 0.0
            nodes.append(PipelineGraphNode(
                node_id=span.op_id,
                label=_node_label(span.op_name),
                op_type=span.op_type,
                depth=depth,
                branch_id=branch_id,
                candidate_count=candidate_count,
                metrics=metrics,
                is_merge=len(fired_parents) >= 2,
            ))
            for parent in fired_parents:
                kind = "fan_in" if len(fired_parents) >= 2 else "flow"
                edges.append(PipelineGraphEdge(source=parent, target=span.op_id, kind=kind))

        nodes.sort(key=lambda n: (n.depth, n.node_id))
        graphs.append(PipelineGraph(pipeline_id=pipeline_id, nodes=nodes, edges=edges))
    return graphs
