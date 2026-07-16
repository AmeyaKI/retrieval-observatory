from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional

from retrieval_observatory.pipeline.graph_contract import (
    GraphMetricValue,
    GraphLatencyStats,
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


def _metric_value(entry: Optional[Dict[str, Any]], *, with_k: bool = False) -> Optional[GraphMetricValue]:
    if not entry:
        return None
    return GraphMetricValue(
        mean=entry.get("mean"),
        ci_low=entry.get("ci_low"),
        ci_high=entry.get("ci_high"),
        k=entry.get("k") if with_k else None,
    )


def _percentile(values: List[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _union_depths(parents_by_op: Dict[str, set[str]], warnings: List[str]) -> Dict[str, int]:
    cache: Dict[str, int] = {}

    def depth_of(op_id: str, visiting: frozenset[str]) -> int:
        if op_id in cache:
            return cache[op_id]
        if op_id in visiting:
            warnings.append(f"Cycle detected while projecting operator '{op_id}'.")
            return 0
        parents = [parent for parent in parents_by_op.get(op_id, set()) if parent in parents_by_op]
        depth = 0 if not parents else 1 + max(depth_of(parent, visiting | {op_id}) for parent in parents)
        cache[op_id] = depth
        return depth

    return {op_id: depth_of(op_id, frozenset()) for op_id in parents_by_op}


def build_pipeline_graphs(
    aggregated: Dict[str, Any],
    traces: list,
    *,
    projection_mode: str = "run_union",
    trace_id: Optional[str] = None,
) -> List[PipelineGraph]:
    """Project persisted traces into a run-union or exact-trace graph contract."""
    if projection_mode not in {"run_union", "trace"}:
        raise ValueError("projection_mode must be 'run_union' or 'trace'")
    if projection_mode == "trace":
        if trace_id is None:
            if len(traces) != 1:
                raise ValueError("trace projection requires trace_id when multiple traces are provided")
        else:
            traces = [trace for trace in traces if trace.trace_id == trace_id]

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

    # Every terminal state contributes topology/status evidence. Quality metrics remain
    # independently availability-gated by the metrics engine.
    traces_by_pipeline: Dict[str, list] = defaultdict(list)
    for trace in traces:
        traces_by_pipeline[trace.pipeline_id].append(trace)

    graphs: List[PipelineGraph] = []
    for pipeline_id, pipeline_traces in sorted(traces_by_pipeline.items()):
        warnings: List[str] = []
        span_samples: Dict[str, list] = defaultdict(list)
        parents_by_op: Dict[str, set[str]] = defaultdict(set)
        edge_trace_keys: Dict[tuple[str, str], set[str]] = defaultdict(set)
        final_counts: Counter[str] = Counter()
        op_types: Dict[str, set[str]] = defaultdict(set)

        for trace_index, trace in enumerate(pipeline_traces):
            trace_key = trace.trace_id or f"trace-{trace_index}"
            spans_by_id: Dict[str, Any] = {}
            for span in trace.spans:
                if span.op_id in spans_by_id:
                    warnings.append(f"Trace '{trace_key}' repeats operator ID '{span.op_id}'.")
                    continue
                spans_by_id[span.op_id] = span
                span_samples[span.op_id].append((trace_key, span))
                parents_by_op.setdefault(span.op_id, set())
                op_types[span.op_id].add(str(span.op_type))
            for span in spans_by_id.values():
                for parent in span.parent_ids:
                    if parent not in spans_by_id:
                        warnings.append(
                            f"Trace '{trace_key}' references missing parent '{parent}' for '{span.op_id}'."
                        )
                        continue
                    parents_by_op[span.op_id].add(parent)
                    edge_trace_keys[(parent, span.op_id)].add(trace_key)
            if trace.final_op_id:
                if trace.final_op_id in spans_by_id:
                    final_counts[trace.final_op_id] += 1
                else:
                    warnings.append(
                        f"Trace '{trace_key}' final_op_id '{trace.final_op_id}' is not present in its spans."
                    )

        if not span_samples:
            continue
        for op_id, values in op_types.items():
            if len(values) > 1:
                warnings.append(f"Operator '{op_id}' has inconsistent types: {sorted(values)}.")

        depth_by_op = _union_depths(parents_by_op, warnings)
        nodes_at_depth: Dict[int, int] = defaultdict(int)
        for depth in depth_by_op.values():
            nodes_at_depth[depth] += 1

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
        trace_count = len(pipeline_traces)
        for op_id, samples in span_samples.items():
            sample_spans = [span for _, span in samples]
            representative = sample_spans[0]
            depth = depth_by_op[op_id]
            branch_id = None if nodes_at_depth[depth] == 1 else op_id
            observed_count = len({trace_key for trace_key, _ in samples})
            status_counts = Counter(str(span.status) for span in sample_spans)
            latency_values = [max(0.0, float(span.latency_ms)) for span in sample_spans]
            metrics = GraphNodeMetrics(
                ndcg10=_metric_value(metric_index.get((pipeline_id, depth, "ndcg", 10, branch_id))),
                recall=_best_recall(depth, branch_id),
                latency_p50=_metric_value(metric_index.get((pipeline_id, depth, "latency_p50", 0, branch_id))),
            )
            metric_available = any(value is not None for value in (metrics.ndcg10, metrics.recall, metrics.latency_p50))
            grouped_inputs = [getattr(span, "input_groups", {}) for span in sample_spans]
            parent_ids = set().union(*(set(groups) for groups in grouped_inputs))
            parent_candidate_counts = {
                parent_id: mean(len(groups.get(parent_id, ())) for groups in grouped_inputs)
                for parent_id in sorted(parent_ids)
            }
            input_counts = [
                sum(len(candidates) for candidates in groups.values()) if groups else len(span.inputs)
                for span, groups in zip(sample_spans, grouped_inputs)
            ]
            nodes.append(PipelineGraphNode(
                node_id=op_id,
                label=_node_label(representative.op_name),
                op_type=representative.op_type,
                depth=depth,
                branch_id=branch_id,
                candidate_count=mean(len(span.outputs) for span in sample_spans),
                metrics=metrics,
                is_merge=len(parents_by_op[op_id]) >= 2,
                input_candidate_count=mean(input_counts),
                parent_candidate_counts=parent_candidate_counts,
                observed_count=observed_count,
                trace_coverage=observed_count / trace_count if trace_count else 0.0,
                fire_rate=status_counts.get("FIRED", 0) / trace_count if trace_count else 0.0,
                status_counts=dict(status_counts),
                cache_hits=sum(bool(span.params.get("cache_hit")) for span in sample_spans),
                latency=GraphLatencyStats(
                    count=len(latency_values),
                    mean_ms=mean(latency_values) if latency_values else None,
                    p50_ms=_percentile(latency_values, 0.50),
                    p95_ms=_percentile(latency_values, 0.95),
                ),
                is_final_output=final_counts[op_id] > 0,
                final_output_count=final_counts[op_id],
                configured=None,
                availability={
                    "topology": "measured",
                    "metrics": "measured" if metric_available else "unavailable",
                    "candidate_inputs": "measured" if any(input_counts) else "unavailable",
                },
            ))

        edges: List[PipelineGraphEdge] = []
        for (source, target), observed_traces in sorted(edge_trace_keys.items()):
            target_observed = len({trace_key for trace_key, _ in span_samples[target]})
            observed_count = len(observed_traces)
            edges.append(PipelineGraphEdge(
                source=source,
                target=target,
                kind="fan_in" if len(parents_by_op[target]) >= 2 else "flow",
                observed_count=observed_count,
                trace_coverage=observed_count / trace_count if trace_count else 0.0,
                conditional=observed_count < target_observed or observed_count < trace_count,
            ))

        nodes.sort(key=lambda n: (n.depth, n.node_id))
        status_counts = Counter(str(trace.status) for trace in pipeline_traces)
        graphs.append(PipelineGraph(
            pipeline_id=pipeline_id,
            nodes=nodes,
            edges=edges,
            projection_mode=projection_mode,
            trace_count=trace_count,
            complete_trace_count=status_counts.get("OK", 0),
            status_counts=dict(status_counts),
            final_output_ids=sorted(final_counts),
            warnings=sorted(set(warnings)),
        ))
    return graphs
