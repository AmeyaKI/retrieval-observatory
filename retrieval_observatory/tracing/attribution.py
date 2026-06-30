from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from retrieval_observatory.tracing.model_v2 import ReplayPolicy, RetrievalTraceV2
from retrieval_observatory.tracing.replay import without_operator


@dataclass
class MarginalResult:
    op_id: str
    segment: str
    metric: str
    k: int
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    n_pairs: int
    replay_policy: ReplayPolicy
    result_status: str
    low_power: bool = False
    fire_rate: float = 0.0


def segment_key(trace: RetrievalTraceV2) -> str:
    for span in trace.spans:
        if span.op_type == "GATE" and span.gate_values:
            pieces = [f"{k}={v}" for k, v in sorted(span.gate_values.items())]
            return "|".join(pieces)
    return "baseline"


def segments(traces: List[RetrievalTraceV2], top_n: int = 20) -> List[str]:
    counts: Dict[str, int] = {}
    for trace in traces:
        key = segment_key(trace)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    names = [name for name, _ in ordered[:top_n]]
    if len(ordered) > top_n:
        names.append("other")
    return names


def _recall_at_k(doc_ids: List[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(doc_ids[:k]) & relevant) / float(len(relevant))


def operator_fire_rate(op_id: str, traces: List[RetrievalTraceV2]) -> float:
    if not traces:
        return 0.0
    fired = 0
    for trace in traces:
        span = next((s for s in trace.spans if s.op_id == op_id), None)
        if span and span.status == "FIRED":
            fired += 1
    return fired / float(len(traces))


def operator_marginal_contribution(
    traces: List[RetrievalTraceV2],
    op_id: str,
    qrels: Dict[str, Dict[str, int] | List[str] | set[str]],
    metric: str = "recall",
    k: int = 10,
) -> List[MarginalResult]:
    if metric != "recall":
        raise ValueError("Only recall attribution is currently supported")
    out: List[MarginalResult] = []
    traces_by_segment: Dict[str, List[RetrievalTraceV2]] = {}
    for trace in traces:
        traces_by_segment.setdefault(segment_key(trace), []).append(trace)

    for seg_name, seg_traces in traces_by_segment.items():
        with_scores: List[float] = []
        without_scores: List[float] = []
        replay_policy: ReplayPolicy = "NOT_REPLAYABLE"

        for trace in seg_traces:
            span = next((s for s in trace.spans if s.op_id == op_id), None)
            if span is None or span.status != "FIRED":
                continue
            replay_policy = span.replay_policy
            rel = qrels.get(trace.query_id) or {}
            rel_set = set(rel.keys()) if isinstance(rel, dict) else set(rel)
            if not rel_set:
                continue
            final = trace.spans[-1].outputs if trace.spans else []
            with_scores.append(_recall_at_k([c.doc_id for c in final], rel_set, k))
            cf = without_operator(trace, op_id)
            cf_final = cf.spans[-1].outputs if cf.spans else []
            without_scores.append(_recall_at_k([c.doc_id for c in cf_final], rel_set, k))

        n_pairs = min(len(with_scores), len(without_scores))
        if n_pairs == 0:
            out.append(
                MarginalResult(
                    op_id=op_id,
                    segment=seg_name,
                    metric=metric,
                    k=k,
                    delta=None,
                    ci_low=None,
                    ci_high=None,
                    n_pairs=0,
                    replay_policy=replay_policy,
                    result_status="not_applicable",
                    fire_rate=operator_fire_rate(op_id, seg_traces),
                )
            )
            continue

        delta = sum(a - b for a, b in zip(with_scores, without_scores)) / float(n_pairs)
        out.append(
            MarginalResult(
                op_id=op_id,
                segment=seg_name,
                metric=metric,
                k=k,
                delta=delta,
                ci_low=None,
                ci_high=None,
                n_pairs=n_pairs,
                replay_policy=replay_policy,
                result_status="measured",
                low_power=n_pairs < 20,
                fire_rate=operator_fire_rate(op_id, seg_traces),
            )
        )
    return out
