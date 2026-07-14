from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from retrieval_observatory.tracing.attribution import _find_final_span, _metric_at_k
from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2
from retrieval_observatory.tracing.replay import ReplayAssumptions, simulate_without_operator


@dataclass
class SimulationResult:
    """Estimated impact of a proposed pipeline change, before the user applies it.

    Built on the same counterfactual-replay machinery as attribution, so the estimate
    is grounded in observed traces. `assumptions` makes the estimate's basis inspectable
    (Pillar 2 + Pillar 5) — the goal is informed decision-making, not perfect prediction.
    """

    change: str
    op_id: str
    metric: str
    k: int
    baseline_mean: Optional[float]
    simulated_mean: Optional[float]
    delta: Optional[float]
    n_queries: int
    result_status: str = "replayed"
    evidence_class: str = "replayed"
    reason: Optional[str] = None
    unsupported_descendants: List[str] = field(default_factory=list)
    assumptions: Optional[Dict] = None
    caveats: List[str] = field(default_factory=list)


def simulate_operator_removal(
    traces: List[RetrievalTraceV2],
    qrels: Dict[str, object],
    op_id: str,
    *,
    metric: str = "recall",
    k: int = 10,
) -> Optional[SimulationResult]:
    """Estimate the quality impact of removing `op_id` (e.g. a reranker or filter).

    Positive delta means removing the operator *helps* (it was hurting quality);
    negative means the operator is contributing. Returns None if no trace fires it.
    """
    baseline_scores: List[float] = []
    simulated_scores: List[float] = []
    assumptions: Optional[ReplayAssumptions] = None

    for trace in traces:
        span = next((s for s in trace.spans if s.op_id == op_id and s.status == "FIRED"), None)
        if span is None:
            continue
        qrel = qrels.get(trace.query_id)
        if not qrel:
            continue
        replay = simulate_without_operator(trace, op_id)
        if assumptions is None:
            assumptions = replay.assumptions
        if replay.status == "indeterminate" or replay.trace is None:
            return SimulationResult(
                change=f"remove_operator:{op_id}",
                op_id=op_id,
                metric=metric,
                k=k,
                baseline_mean=None,
                simulated_mean=None,
                delta=None,
                n_queries=0,
                result_status="indeterminate",
                evidence_class="unavailable",
                reason=replay.reason,
                unsupported_descendants=replay.unsupported_descendants,
                assumptions=replay.assumptions.__dict__,
                caveats=list(replay.assumptions.caveats),
            )
        final = _find_final_span(trace)
        baseline_scores.append(_metric_at_k([c.doc_id for c in (final.outputs if final else [])], qrel, metric, k))
        cf_final = _find_final_span(replay.trace)
        simulated_scores.append(_metric_at_k([c.doc_id for c in (cf_final.outputs if cf_final else [])], qrel, metric, k))

    n = min(len(baseline_scores), len(simulated_scores))
    if n == 0:
        return None
    baseline_mean = sum(baseline_scores) / n
    simulated_mean = sum(simulated_scores) / n
    return SimulationResult(
        change=f"remove_operator:{op_id}",
        op_id=op_id,
        metric=metric,
        k=k,
        baseline_mean=round(baseline_mean, 4),
        simulated_mean=round(simulated_mean, 4),
        delta=round(simulated_mean - baseline_mean, 4),
        n_queries=n,
        assumptions=assumptions.__dict__ if assumptions else None,
        caveats=list(assumptions.caveats) if assumptions else [],
    )
