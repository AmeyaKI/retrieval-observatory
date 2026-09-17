"""Self-inflicted recall loss: which operator displaced a gold document the pipeline had found.

Implements the definitions pre-registered in ``results/study/PREREGISTRATION.md`` §3. Every
statistic is computed from the ranks the runner recorded on each span's ``input_groups`` and
``outputs``; nothing is re-derived from scores.

Per (query, gold document) pair, with delivery window ``k`` (default 10):

* **surfaced** — the gold appears in some FIRED span's outputs at any rank.
* **delivered** — the gold is at rank ≤ k in a final span's outputs.
* **displacement** — an operator whose input has the gold at rank ≤ k (in any input group)
  and whose output does not (rank > k or absent). The final top-k cut is not an operator.
* **destroyed** — surfaced, in the window at some output, not delivered. Attributed to the
  *last* displacing operator; the *first* is kept for the recovery analysis.
* **recovery** — displaced, then back at rank ≤ k at a later operator's output;
  a later displacement of a recovered gold is a re-displacement.

Rates carry percentile cluster-bootstrap intervals that resample *queries* with replacement,
so the golds of one query stay together.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

DELIVERY_K = 10
FIXED_SURFACED_K = 50
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 17

OUTCOMES: Tuple[str, ...] = ("delivered", "destroyed", "never_surfaced", "surfaced_never_in_window", "unattributed")

# PREREGISTRATION.md §4: classes are mapped from op_type, never from names.
OPERATOR_CLASS_BY_OP_TYPE: Mapping[str, str] = {
    "FUSE": "fusion",
    "RERANK": "rerank",
    "FILTER": "filter/dedup",
    "GATE": "routing/merge",
    "EXPAND": "expand",
}
OPERATOR_CLASSES: Tuple[str, ...] = ("fusion", "rerank", "filter/dedup", "routing/merge", "expand", "other")


def operator_class(op_type: str) -> str:
    return OPERATOR_CLASS_BY_OP_TYPE.get(str(op_type), "other")


@dataclass(frozen=True)
class Displacement:
    op_id: str
    op_type: str
    operator_class: str


@dataclass
class GoldEvent:
    """What happened to one gold document in one query's trace."""

    query_id: str
    doc_id: str
    outcome: str
    surfaced: bool
    surfaced_within_fixed_k: bool
    ever_in_window: bool
    first_displacer: Optional[Displacement] = None
    last_displacer: Optional[Displacement] = None
    displacements: int = 0
    recoveries: int = 0
    redisplacements: int = 0
    set_refound: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExcludedQuery:
    query_id: str
    reason: str
    gold_count: int


@dataclass
class RunAttribution:
    events: List[GoldEvent]
    excluded: List[ExcludedQuery]
    k: int
    fixed_k: int

    @property
    def completeness(self) -> Optional[float]:
        """Share of (query, gold) pairs whose trace was usable (PREREGISTRATION.md §2 rule 1)."""
        excluded_pairs = sum(item.gold_count for item in self.excluded)
        total = len(self.events) + excluded_pairs
        return None if total == 0 else len(self.events) / total


@dataclass
class Rate:
    value: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    numerator: int
    denominator: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------------------
# Per-trace attribution
# --------------------------------------------------------------------------------------


def _input_rank(candidate: Candidate) -> int:
    return candidate.input_rank if candidate.input_rank is not None else candidate.rank


def _output_rank(candidate: Candidate) -> int:
    return candidate.output_rank if candidate.output_rank is not None else candidate.rank


def _topological(spans: Sequence[OperatorSpan]) -> List[OperatorSpan]:
    by_id = {span.op_id: span for span in spans}
    ordered: List[OperatorSpan] = []
    seen: set = set()

    def visit(span: OperatorSpan) -> None:
        if span.op_id in seen:
            return
        seen.add(span.op_id)
        for parent_id in span.parent_ids:
            if parent_id in by_id:
                visit(by_id[parent_id])
        ordered.append(span)

    for span in spans:
        visit(span)
    return ordered


def _final_spans(trace: RetrievalTrace, fired: Sequence[OperatorSpan]) -> List[OperatorSpan]:
    if trace.final_op_ids:
        return [span for span in fired if span.op_id in trace.final_op_ids]
    parents = {parent for span in fired for parent in span.parent_ids}
    sinks = [span for span in fired if span.op_id not in parents]
    if len(sinks) == 1:
        return sinks
    return list(fired[-1:])


def lineage_partial(trace: RetrievalTrace) -> bool:
    capture = trace.capture
    return bool(
        capture.lineage_evidence in {"partial", "unavailable"} or capture.candidates_truncated or capture.omitted_field_count
    )


def gold_events(
    trace: RetrievalTrace,
    gold_ids: Iterable[str],
    *,
    k: int = DELIVERY_K,
    fixed_k: int = FIXED_SURFACED_K,
) -> List[GoldEvent]:
    """Classify every gold document of one trace. The trace must be OK with complete lineage."""
    fired = _topological([span for span in trace.spans if span.status == "FIRED"])
    finals = _final_spans(trace, fired)
    events: List[GoldEvent] = []
    for doc_id in gold_ids:
        events.append(_gold_event(trace.query_id, doc_id, fired, finals, k, fixed_k))
    return events


def _gold_event(
    query_id: str,
    doc_id: str,
    fired: Sequence[OperatorSpan],
    finals: Sequence[OperatorSpan],
    k: int,
    fixed_k: int,
) -> GoldEvent:
    surfaced = False
    surfaced_fixed = False
    ever_in_window = False
    displacers: List[Displacement] = []
    recoveries = 0
    redisplacements = 0
    displaced_now = False
    dropped_from_set = False
    set_refound = False

    for span in fired:
        at_input = [c for group in span.input_groups.values() for c in group if c.doc_id == doc_id]
        at_output = next((c for c in span.outputs if c.doc_id == doc_id), None)
        in_window_at_input = any(_input_rank(c) <= k for c in at_input)
        out_rank = _output_rank(at_output) if at_output is not None else None

        if at_output is not None:
            surfaced = True
            if dropped_from_set:
                set_refound = True
            surfaced_fixed = surfaced_fixed or out_rank <= fixed_k
        elif at_input:
            dropped_from_set = True

        in_window_at_output = out_rank is not None and out_rank <= k
        if in_window_at_output:
            ever_in_window = True
            if displaced_now:
                recoveries += 1
                displaced_now = False
        elif in_window_at_input:
            displacers.append(Displacement(span.op_id, str(span.op_type), operator_class(span.op_type)))
            if recoveries:
                redisplacements += 1
            displaced_now = True

    delivered = any(
        _output_rank(c) <= k for span in finals for c in span.outputs if c.doc_id == doc_id
    )
    if delivered:
        outcome = "delivered"
    elif not surfaced:
        outcome = "never_surfaced"
    elif not ever_in_window:
        outcome = "surfaced_never_in_window"
    elif displacers:
        outcome = "destroyed"
    else:
        # In the window on a branch that never reached a final operator: a miss, but no
        # operator displaced it, so it is reported rather than attributed.
        outcome = "unattributed"

    return GoldEvent(
        query_id=query_id,
        doc_id=doc_id,
        outcome=outcome,
        surfaced=surfaced,
        surfaced_within_fixed_k=surfaced_fixed,
        ever_in_window=ever_in_window,
        first_displacer=displacers[0] if displacers else None,
        last_displacer=displacers[-1] if displacers else None,
        displacements=len(displacers),
        recoveries=recoveries,
        redisplacements=redisplacements,
        set_refound=set_refound,
    )


def _relevant_ids(raw: Mapping[str, int] | Iterable[str]) -> List[str]:
    if isinstance(raw, Mapping):
        return [doc_id for doc_id, grade in raw.items() if int(grade) > 0]
    return list(raw)


def attribute_run(
    traces: Sequence[RetrievalTrace],
    qrels: Mapping[str, Mapping[str, int] | Iterable[str]],
    *,
    k: int = DELIVERY_K,
    fixed_k: int = FIXED_SURFACED_K,
) -> RunAttribution:
    """Attribute every (query, gold) pair of a run. Unusable traces are excluded and counted."""
    events: List[GoldEvent] = []
    excluded: List[ExcludedQuery] = []
    for trace in traces:
        gold = _relevant_ids(qrels.get(trace.query_id, {}))
        if not gold:
            continue
        if trace.status != "OK":
            excluded.append(ExcludedQuery(trace.query_id, f"trace status {trace.status}", len(gold)))
            continue
        if lineage_partial(trace):
            excluded.append(ExcludedQuery(trace.query_id, "lineage partial", len(gold)))
            continue
        events.extend(gold_events(trace, gold, k=k, fixed_k=fixed_k))
    return RunAttribution(events=events, excluded=excluded, k=k, fixed_k=fixed_k)


# --------------------------------------------------------------------------------------
# Rates with cluster-bootstrap intervals
# --------------------------------------------------------------------------------------


def _per_query(events: Sequence[GoldEvent], predicate) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for event in events:
        counts[event.query_id] += int(bool(predicate(event)))
    return counts


def _ratio(numerator: np.ndarray, denominator: np.ndarray) -> float:
    total = float(denominator.sum())
    return float(numerator.sum()) / total if total else float("nan")


def bootstrap_rate(
    events: Sequence[GoldEvent],
    numerator,
    denominator,
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> Rate:
    """Ratio of event counts with a percentile bootstrap over queries (clusters).

    ``numerator`` and ``denominator`` are predicates on a `GoldEvent`; the rate is
    Σ numerator ÷ Σ denominator over all pairs. Resamples with an empty denominator are
    dropped from the interval.
    """
    query_ids = sorted({event.query_id for event in events})
    num_by_query = _per_query(events, numerator)
    den_by_query = _per_query(events, denominator)
    num = np.array([num_by_query[q] for q in query_ids], dtype=float)
    den = np.array([den_by_query[q] for q in query_ids], dtype=float)
    total_den = int(den.sum())
    total_num = int(num.sum())
    if total_den == 0:
        return Rate(None, None, None, total_num, 0)
    low, high = _cluster_interval([(num, den)], lambda parts: _ratio(*parts[0]), n_resamples, seed)
    return Rate(total_num / total_den, low, high, total_num, total_den)


def _cluster_interval(
    arrays: Sequence[Tuple[np.ndarray, np.ndarray]],
    statistic,
    n_resamples: int,
    seed: int,
    ci: float = 0.95,
) -> Tuple[Optional[float], Optional[float]]:
    size = len(arrays[0][0])
    if size == 0 or n_resamples < 1:
        return None, None
    rng = np.random.default_rng(seed)
    values = np.empty(n_resamples, dtype=float)
    for index in range(n_resamples):
        sample = rng.integers(0, size, size=size)
        values[index] = statistic([(num[sample], den[sample]) for num, den in arrays])
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, None
    alpha = (1.0 - ci) / 2.0
    low, high = np.quantile(finite, [alpha, 1.0 - alpha])
    return float(low), float(high)


def self_inflicted_difference(
    events_a: Sequence[GoldEvent],
    events_b: Sequence[GoldEvent],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> Tuple[Rate, int]:
    """Self-inflicted fraction of B minus A on the queries both share, with a paired cluster bootstrap.

    Returns the difference as a `Rate` (numerator/denominator are B's counts) and the number
    of queries present in only one side, which were dropped.
    """
    is_miss = _is_miss
    is_destroyed = _is_destroyed
    shared = sorted({e.query_id for e in events_a} & {e.query_id for e in events_b})
    dropped = len(({e.query_id for e in events_a} | {e.query_id for e in events_b}) - set(shared))
    if not shared:
        return Rate(None, None, None, 0, 0), dropped

    def arrays(events: Sequence[GoldEvent]) -> Tuple[np.ndarray, np.ndarray]:
        num_by_query = _per_query(events, is_destroyed)
        den_by_query = _per_query(events, is_miss)
        return (
            np.array([num_by_query[q] for q in shared], dtype=float),
            np.array([den_by_query[q] for q in shared], dtype=float),
        )

    a_num, a_den = arrays(events_a)
    b_num, b_den = arrays(events_b)
    if a_den.sum() == 0 or b_den.sum() == 0:
        return Rate(None, None, None, int(b_num.sum()), int(b_den.sum())), dropped
    value = _ratio(b_num, b_den) - _ratio(a_num, a_den)
    low, high = _cluster_interval(
        [(a_num, a_den), (b_num, b_den)],
        lambda parts: _ratio(*parts[1]) - _ratio(*parts[0]),
        n_resamples,
        seed,
    )
    return Rate(value, low, high, int(b_num.sum()), int(b_den.sum())), dropped


def _is_miss(event: GoldEvent) -> bool:
    return event.outcome != "delivered"


def _is_destroyed(event: GoldEvent) -> bool:
    return event.outcome == "destroyed"


# --------------------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------------------


@dataclass
class LossSummary:
    k: int
    fixed_k: int
    n_queries: int
    n_pairs: int
    outcome_counts: Dict[str, int]
    self_inflicted_fraction: Rate
    never_surfaced_fraction: Rate
    surfaced_never_in_window_fraction: Rate
    unattributed_fraction: Rate
    # Fixed-K variant: the same misses split by whether the gold was ever within `fixed_k`.
    # The self-inflicted fraction is unchanged by construction (in-window implies within K).
    never_surfaced_fraction_fixed_k: Rate
    surfaced_never_in_window_fraction_fixed_k: Rate
    loss_share_by_class: Dict[str, Rate]
    loss_share_by_operator: Dict[str, Rate]
    displaced_pairs: int
    recovery_rate: Rate
    redisplacement_rate: Rate
    destroyed_first_differs_from_last: int
    set_refound_pairs: int
    n_resamples: int
    seed: int
    excluded_queries: List[Dict[str, Any]] = field(default_factory=list)
    completeness: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        return payload


def summarize(
    attribution: RunAttribution | Sequence[GoldEvent],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> LossSummary:
    if isinstance(attribution, RunAttribution):
        events = attribution.events
        excluded = [asdict(item) for item in attribution.excluded]
        completeness = attribution.completeness
        k, fixed_k = attribution.k, attribution.fixed_k
    else:
        events, excluded, completeness, k, fixed_k = list(attribution), [], None, DELIVERY_K, FIXED_SURFACED_K

    def rate(numerator, denominator) -> Rate:
        return bootstrap_rate(events, numerator, denominator, n_resamples=n_resamples, seed=seed)

    counts = {outcome: sum(1 for e in events if e.outcome == outcome) for outcome in OUTCOMES}
    destroyed = [e for e in events if e.outcome == "destroyed"]
    classes = sorted({e.last_displacer.operator_class for e in destroyed} | set(OPERATOR_CLASSES))
    operators = sorted({e.last_displacer.op_id for e in destroyed})
    displaced = [e for e in events if e.displacements > 0]

    return LossSummary(
        k=k,
        fixed_k=fixed_k,
        n_queries=len({e.query_id for e in events}),
        n_pairs=len(events),
        outcome_counts=counts,
        self_inflicted_fraction=rate(_is_destroyed, _is_miss),
        never_surfaced_fraction=rate(lambda e: e.outcome == "never_surfaced", _is_miss),
        surfaced_never_in_window_fraction=rate(lambda e: e.outcome == "surfaced_never_in_window", _is_miss),
        unattributed_fraction=rate(lambda e: e.outcome == "unattributed", _is_miss),
        never_surfaced_fraction_fixed_k=rate(lambda e: _is_miss(e) and not e.surfaced_within_fixed_k, _is_miss),
        surfaced_never_in_window_fraction_fixed_k=rate(
            lambda e: e.outcome in {"never_surfaced", "surfaced_never_in_window"} and e.surfaced_within_fixed_k,
            _is_miss,
        ),
        loss_share_by_class={
            name: rate(lambda e, name=name: _is_destroyed(e) and e.last_displacer.operator_class == name, _is_destroyed)
            for name in classes
        },
        loss_share_by_operator={
            op_id: rate(lambda e, op_id=op_id: _is_destroyed(e) and e.last_displacer.op_id == op_id, _is_destroyed)
            for op_id in operators
        },
        displaced_pairs=len(displaced),
        recovery_rate=rate(lambda e: e.recoveries > 0, lambda e: e.displacements > 0),
        redisplacement_rate=rate(lambda e: e.redisplacements > 0, lambda e: e.recoveries > 0),
        destroyed_first_differs_from_last=sum(1 for e in destroyed if e.first_displacer != e.last_displacer),
        set_refound_pairs=sum(1 for e in events if e.set_refound),
        n_resamples=n_resamples,
        seed=seed,
        excluded_queries=excluded,
        completeness=completeness,
    )
