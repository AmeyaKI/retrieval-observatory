from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from retrieval_observatory.metrics.ranking import average_precision, ndcg_at_k, ndcg_at_k_graded, precision_at_k
from retrieval_observatory.metrics.recall import recall_at_k
from retrieval_observatory.metrics.significance import benjamini_hochberg, bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.tracing.model import ReplayPolicy, RetrievalTrace
from retrieval_observatory.tracing.replay import simulate_without_operator

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
    significant: Optional[bool] = None
    p_value: Optional[float] = None
    q_value: Optional[float] = None
    evidence_class: str = "unavailable"
    reason: Optional[str] = None
    unsupported_descendants: List[str] = field(default_factory=list)
    assumptions: Optional[Dict[str, object]] = None


def _find_final_span(trace: RetrievalTrace):
    """Return the terminal span using declared final operators or sink detection."""
    if trace.final_op_ids:
        for span in trace.spans:
            if span.op_id in trace.final_op_ids:
                return span
    if not trace.spans:
        return None
    all_parent_ids: Set[str] = set()
    for span in trace.spans:
        all_parent_ids.update(span.parent_ids)
    sinks = [s for s in trace.spans if s.op_id not in all_parent_ids]
    if len(sinks) == 1:
        return sinks[0]
    return trace.spans[-1]


def segment_key(trace: RetrievalTrace) -> str:
    merged: Dict[str, object] = {}
    for span in trace.spans:
        if span.op_type == "GATE" and span.gate_values:
            merged.update(span.gate_values)
    if not merged:
        return "baseline"
    return "|".join(f"{k}={v}" for k, v in sorted(merged.items()))


def segments(traces: List[RetrievalTrace], top_n: int = 20) -> List[str]:
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


def operator_fire_rate(op_id: str, traces: List[RetrievalTrace]) -> float:
    if not traces:
        return 0.0
    fired = 0
    for trace in traces:
        span = next((s for s in trace.spans if s.op_id == op_id), None)
        if span and span.status == "FIRED":
            fired += 1
    return fired / float(len(traces))


def operator_marginal_contribution(
    traces: List[RetrievalTrace],
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

    seg_names = segments(traces)
    traces_by_segment: Dict[str, List[RetrievalTrace]] = {}
    for trace in traces:
        key = segment_key(trace)
        if key not in seg_names and "other" in seg_names:
            key = "other"
        traces_by_segment.setdefault(key, []).append(trace)

    out: List[MarginalResult] = []
    all_p_values: List[float] = []
    result_p_index: List[int] = []

    for seg_name in seg_names:
        seg_traces = traces_by_segment.get(seg_name, [])
        with_scores: List[float] = []
        without_scores: List[float] = []
        replay_policy: ReplayPolicy = "NOT_REPLAYABLE"
        indeterminate_reason: Optional[str] = None
        unsupported_descendants: Set[str] = set()
        assumptions: Optional[Dict[str, object]] = None

        for trace in seg_traces:
            span = next((s for s in trace.spans if s.op_id == op_id), None)
            if span is None or span.status != "FIRED":
                continue
            replay_policy = span.replay_policy
            qrel = qrels.get(trace.query_id)
            if not qrel or not _relevant_set(qrel):
                continue
            final_span = _find_final_span(trace)
            replay = simulate_without_operator(trace, op_id)
            assumptions = dict(replay.assumptions.__dict__)
            if replay.status == "indeterminate" or replay.trace is None:
                indeterminate_reason = replay.reason or "Replay is unsupported."
                unsupported_descendants.update(replay.unsupported_descendants)
                continue
            final = final_span.outputs if final_span else []
            with_scores.append(_metric_at_k([c.doc_id for c in final], qrel, metric, k))
            cf_final_span = _find_final_span(replay.trace)
            cf_final = cf_final_span.outputs if cf_final_span else []
            without_scores.append(_metric_at_k([c.doc_id for c in cf_final], qrel, metric, k))

        if indeterminate_reason is not None:
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
                    result_status="indeterminate",
                    fire_rate=operator_fire_rate(op_id, seg_traces),
                    evidence_class="unavailable",
                    reason=indeterminate_reason,
                    unsupported_descendants=sorted(unsupported_descendants),
                    assumptions=assumptions,
                )
            )
            continue

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
                    evidence_class="unavailable",
                    reason="No fired operator trace had usable relevance judgments.",
                    assumptions=assumptions,
                )
            )
            continue

        pair_deltas = [a - b for a, b in zip(with_scores, without_scores)]
        delta = sum(pair_deltas) / float(n_pairs)
        ci_low: float | None = None
        ci_high: float | None = None
        p_value: float | None = None
        if n_pairs >= n_power_threshold:
            ci_low, ci_high = bootstrap_ci(pair_deltas, n_resamples=n_bootstrap)
            p_value = paired_bootstrap_test(with_scores[:n_pairs], without_scores[:n_pairs], n_resamples=n_bootstrap)
            result_p_index.append(len(out))
            all_p_values.append(p_value)

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
                result_status="replayed",
                low_power=n_pairs < n_power_threshold,
                fire_rate=operator_fire_rate(op_id, seg_traces),
                p_value=p_value,
                evidence_class="replayed",
                assumptions=assumptions,
            )
        )

    if all_p_values:
        q_values = benjamini_hochberg(all_p_values)
        for q_idx, result_idx in enumerate(result_p_index):
            out[result_idx].q_value = q_values[q_idx]
            out[result_idx].significant = q_values[q_idx] < 0.05

    return out
