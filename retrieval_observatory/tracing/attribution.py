from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from retrieval_observatory.metrics.ranking import average_precision, ndcg_at_k, ndcg_at_k_graded, precision_at_k
from retrieval_observatory.metrics.recall import recall_at_k
from retrieval_observatory.metrics.significance import bootstrap_ci
from retrieval_observatory.tracing.model_v2 import ReplayPolicy, RetrievalTraceV2
from retrieval_observatory.tracing.replay import without_operator

_SUPPORTED_METRICS = frozenset({"recall", "ndcg", "precision", "mrr", "map"})


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


def _relevant_set(raw: Dict[str, int] | List[str] | set[str]) -> Set[str]:
    if isinstance(raw, dict):
        return {doc_id for doc_id, grade in raw.items() if int(grade) > 0}
    return set(raw)


def _graded_qrel(raw: Dict[str, int] | List[str] | set[str]) -> Dict[str, int]:
    if isinstance(raw, dict):
        return {doc_id: int(grade) for doc_id, grade in raw.items()}
    return {doc_id: 1 for doc_id in raw}


def _metric_at_k(
    doc_ids: List[str],
    qrel: Dict[str, int] | List[str] | set[str],
    metric: str,
    k: int,
) -> float:
    relevant = _relevant_set(qrel)
    if not relevant:
        return 0.0
    if metric == "recall":
        return recall_at_k(doc_ids, relevant, k)
    if metric == "ndcg":
        graded = _graded_qrel(qrel)
        if any(int(g) > 1 for g in graded.values()):
            return ndcg_at_k_graded(doc_ids, graded, k)
        return ndcg_at_k(doc_ids, relevant, k)
    if metric == "precision":
        return precision_at_k(doc_ids, relevant, k)
    if metric == "mrr":
        for rank, doc_id in enumerate(doc_ids[:k], start=1):
            if doc_id in relevant:
                return 1.0 / rank
        return 0.0
    if metric == "map":
        return average_precision(doc_ids[:k] if k > 0 else doc_ids, relevant)
    raise ValueError(f"Unsupported metric '{metric}'. Use one of {sorted(_SUPPORTED_METRICS)}")


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
    n_power_threshold: int = 20,
    n_bootstrap: int = 1000,
) -> List[MarginalResult]:
    metric = metric.lower()
    if metric not in _SUPPORTED_METRICS:
        raise ValueError(f"Unsupported metric '{metric}'. Use one of {sorted(_SUPPORTED_METRICS)}")

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
            qrel = qrels.get(trace.query_id)
            if not qrel or not _relevant_set(qrel):
                continue
            final = trace.spans[-1].outputs if trace.spans else []
            with_scores.append(_metric_at_k([c.doc_id for c in final], qrel, metric, k))
            cf = without_operator(trace, op_id)
            cf_final = cf.spans[-1].outputs if cf.spans else []
            without_scores.append(_metric_at_k([c.doc_id for c in cf_final], qrel, metric, k))

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

        pair_deltas = [a - b for a, b in zip(with_scores, without_scores)]
        delta = sum(pair_deltas) / float(n_pairs)
        ci_low: float | None = None
        ci_high: float | None = None
        if n_pairs >= n_power_threshold:
            ci_low, ci_high = bootstrap_ci(pair_deltas, n_resamples=n_bootstrap)

        out.append(
            MarginalResult(
                op_id=op_id,
                segment=seg_name,
                metric=metric,
                k=k,
                delta=delta,
                ci_low=ci_low,
                ci_high=ci_high,
                n_pairs=n_pairs,
                replay_policy=replay_policy,
                result_status="measured",
                low_power=n_pairs < n_power_threshold,
                fire_rate=operator_fire_rate(op_id, seg_traces),
            )
        )
    return out
