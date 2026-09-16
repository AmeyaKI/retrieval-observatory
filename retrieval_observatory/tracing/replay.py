from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Literal, Optional, Sequence, Set

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

_MISS_TYPE_BY_OP_TYPE = {
    "RERANK": "rerank_demotion",
    "FUSE": "fusion_dilution",
    "GENERATE": "generation_ignored_context",
}


@dataclass
class MissAttribution:
    query_id: str
    doc_id: str
    miss_type: str
    op_id: str | None
    confidence: str
    note: str = ""


@dataclass
class ReplayAssumptions:
    """How a counterfactual `without_operator` trace was constructed.

    Exposes the replay strategy so users can inspect assumptions rather than
    treating counterfactual replay as a black box (Pillar 2, "Replay Verification").
    """

    op_id: str
    op_type: str
    strategy: str
    rrf_recomputed: bool = False
    rrf_k: int | None = None
    replay_policy: str = "NOT_REPLAYABLE"
    caveats: List[str] = field(default_factory=list)


@dataclass
class ReplayResult:
    """Typed result for a recorded-output counterfactual projection.

    A projection is only returned when the target and every fired descendant declare
    replay support. This is not operator re-execution and is therefore classified as
    replayed evidence, never measured causal evidence.
    """

    op_id: str
    status: Literal["replayed", "indeterminate"]
    evidence_class: Literal["replayed", "unavailable"]
    trace: Optional[RetrievalTrace]
    assumptions: ReplayAssumptions
    reason: Optional[str] = None
    unsupported_descendants: List[str] = field(default_factory=list)


# Human-readable caveat copy per strategy — written for engineers reading the
# Replay Verification inspector, not for logs.
_STRATEGY_CAVEATS: Dict[str, List[str]] = {
    "boost_restore_pre_boost": [
        "Restored each candidate's pre-boost score from score_components; candidates "
        "lacking a recorded pre_boost score were dropped from the counterfactual.",
    ],
    "expand_origin_filter": [
        "Removed candidates introduced solely by this expansion operator; downstream "
        "scores of surviving candidates were reused, not recomputed.",
    ],
    "filter_passthrough_inputs": [
        "Replaced this filter's output with its input set; downstream operators re-ran "
        "over the un-filtered candidates using their originally observed outputs where possible.",
    ],
    "rerank_passthrough_inputs": [
        "Replaced this reranker's output with its input ordering; original downstream "
        "scores were reused, not recomputed by a real model call.",
    ],
    "passthrough_outputs": [
        "Treated this operator as a no-op, passing its outputs through unchanged.",
    ],
    "fuse_rrf_recompute": [
        "Recomputed reciprocal-rank fusion over the remaining retrieval arms with the "
        "same k constant; per-arm scores were reused, only the fusion was re-run.",
    ],
    "remove_outputs": [
        "Removed this operator's contributed documents from every downstream stage; "
        "downstream re-ranking was not recomputed.",
    ],
}


def replay_assumptions(trace: RetrievalTrace, op_id: str) -> ReplayAssumptions:
    """Classify the counterfactual strategy `without_operator` would use for `op_id`.

    Kept as a standalone side-channel so `without_operator`'s signature (used in the
    attribution hot loop) stays a pure trace->trace function.
    """
    target = next((span for span in trace.spans if span.op_id == op_id), None)
    if target is None:
        raise ValueError(f"Operator '{op_id}' not found in trace")

    fuse_child = None
    if target.op_type == "SOURCE":
        for span in trace.spans:
            if span.op_type == "FUSE" and op_id in span.parent_ids:
                fuse_child = span
                break

    rrf_recomputed = False
    rrf_k: int | None = None
    if target.op_type == "SOURCE" and fuse_child is not None:
        strategy = "fuse_rrf_recompute"
        rrf_recomputed = True
        rrf_k = _rrf_k(fuse_child)
    elif target.op_type == "BOOST":
        strategy = "boost_restore_pre_boost"
    elif target.op_type == "EXPAND":
        strategy = "expand_origin_filter"
    elif target.op_type == "FILTER":
        strategy = "filter_passthrough_inputs"
    elif target.op_type == "RERANK":
        strategy = "rerank_passthrough_inputs"
    elif target.op_type in {"GATE", "TRANSFORM"}:
        strategy = "passthrough_outputs"
    else:
        strategy = "remove_outputs"

    return ReplayAssumptions(
        op_id=op_id,
        op_type=str(target.op_type),
        strategy=strategy,
        rrf_recomputed=rrf_recomputed,
        rrf_k=rrf_k,
        replay_policy=str(target.replay_policy),
        caveats=list(_STRATEGY_CAVEATS.get(strategy, [])),
    )


class _Indeterminate(ValueError):
    """Raised by `without_operator` when the counterfactual cannot be projected honestly.

    Replay is strict: whenever a child operator would have to decide on documents it
    never observed, the projection is refused rather than fabricated.
    `simulate_without_operator` turns this into an ``indeterminate`` `ReplayResult`.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _rrf_k(span: OperatorSpan) -> int:
    """Read the RRF constant; the executor writes ``rrf_k``, older traces wrote ``k``."""
    return int(span.params.get("rrf_k", span.params.get("k", 60)))


def _renumber(candidates: Sequence[Candidate]) -> List[Candidate]:
    """Return copies with ranks renumbered 1..n in the given order."""
    return [
        replace(
            candidate,
            rank=position,
            output_rank=position,
            origin_op_ids=tuple(candidate.origin_op_ids),
            score_components=dict(candidate.score_components),
            metadata=dict(candidate.metadata),
        )
        for position, candidate in enumerate(candidates, start=1)
    ]


def _topological_order(trace: RetrievalTrace) -> List[OperatorSpan]:
    """Spans with every parent before its children, stable w.r.t. trace order."""
    by_id = {span.op_id: span for span in trace.spans}
    ordered: List[OperatorSpan] = []
    seen: Set[str] = set()

    def visit(span: OperatorSpan) -> None:
        if span.op_id in seen:
            return
        seen.add(span.op_id)
        for parent_id in span.parent_ids:
            if parent_id in by_id:
                visit(by_id[parent_id])
        ordered.append(span)

    for span in trace.spans:
        visit(span)
    return ordered


def _descendant_spans(trace: RetrievalTrace, op_id: str) -> List[OperatorSpan]:
    children: Dict[str, Set[str]] = {}
    by_id = {span.op_id: span for span in trace.spans}
    for span in trace.spans:
        for parent_id in span.parent_ids:
            children.setdefault(parent_id, set()).add(span.op_id)
    descendant_ids: Set[str] = set()
    frontier = list(children.get(op_id, set()))
    while frontier:
        current = frontier.pop()
        if current in descendant_ids:
            continue
        descendant_ids.add(current)
        frontier.extend(children.get(current, set()))
    return [by_id[descendant_id] for descendant_id in sorted(descendant_ids) if descendant_id in by_id]


def _clone_span(
    span: OperatorSpan,
    *,
    outputs: Sequence[Candidate] | None = None,
    parent_ids: Sequence[str] | None = None,
) -> OperatorSpan:
    cloned_parents = tuple(parent_ids if parent_ids is not None else span.parent_ids)
    return OperatorSpan(
        op_id=span.op_id,
        op_type=span.op_type,
        op_name=span.op_name,
        parent_ids=cloned_parents,
        status=span.status,
        deterministic=span.deterministic,
        replay_policy=span.replay_policy,
        latency_ms=span.latency_ms,
        input_groups={parent: tuple(span.input_groups.get(parent, ())) for parent in cloned_parents},
        outputs=list(outputs if outputs is not None else span.outputs),
        params=dict(span.params),
        gate_values=dict(span.gate_values),
        input_variant=span.input_variant,
        error=span.error,
    )


def _find_final_span(trace: RetrievalTrace) -> Optional[OperatorSpan]:
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


def _rrf_merge(
    arm_outputs: List[List[Candidate]],
    k: int = 60,
    observed_outputs: Sequence[Candidate] = (),
) -> List[Candidate]:
    """Reciprocal rank fusion across multiple arms."""
    scores: Dict[str, float] = {}
    origins: Dict[str, List[str]] = {}
    components: Dict[str, Dict[str, float]] = {}
    candidate_map: Dict[str, Candidate] = {}
    parent_candidate_ids: Dict[str, List[str]] = {}
    for arm_candidates in arm_outputs:
        for rank_pos, c in enumerate(arm_candidates, start=1):
            rrf_score = 1.0 / (k + rank_pos)
            scores[c.doc_id] = scores.get(c.doc_id, 0.0) + rrf_score
            origins.setdefault(c.doc_id, []).extend(c.origin_op_ids)
            components.setdefault(c.doc_id, {})
            for oid in c.origin_op_ids:
                components[c.doc_id][oid] = rrf_score
            if c.doc_id not in candidate_map:
                candidate_map[c.doc_id] = c
            if c.candidate_id not in parent_candidate_ids.setdefault(c.doc_id, []):
                parent_candidate_ids[c.doc_id].append(c.candidate_id)
    observed_map = {candidate.doc_id: candidate for candidate in observed_outputs}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result: List[Candidate] = []
    for rank_pos, (doc_id, score) in enumerate(ranked, start=1):
        base = observed_map.get(doc_id, candidate_map[doc_id])
        result.append(replace(
            base,
            score=score,
            rank=rank_pos,
            output_rank=rank_pos,
            origin_op_ids=tuple(sorted(set(origins.get(doc_id, [])))),
            score_components=components.get(doc_id, {}),
            add_reason="fused",
            metadata=dict(base.metadata),
            parent_candidate_ids=tuple(parent_candidate_ids.get(doc_id, ())),
            identity_evidence=base.identity_evidence if doc_id in observed_map else "legacy_inferred",
            decision_reason="fused",
            decision_evidence="legacy_inferred",
        ))
    return result


def _replacement_for(target: OperatorSpan) -> List[Candidate] | None:
    """What the removed operator's consumers receive instead of its outputs.

    ``None`` means the operator is a producer (SOURCE or unknown type) whose
    contribution is removed rather than replaced.
    """
    if target.op_type == "BOOST":
        restored: List[Candidate] = []
        for candidate in target.outputs:
            pre = candidate.score_components.get("pre_boost")
            if pre is None:
                continue
            restored.append(replace(
                candidate,
                score=float(pre),
                origin_op_ids=tuple(candidate.origin_op_ids),
                score_components=dict(candidate.score_components),
                metadata=dict(candidate.metadata),
            ))
        return _renumber(sorted(restored, key=lambda c: c.score, reverse=True))
    if target.op_type == "EXPAND":
        return _renumber([
            c for c in target.outputs
            if not (len(c.origin_op_ids) == 1 and c.origin_op_ids[0] == target.op_id)
            and c.add_reason != "expanded"
        ])
    if target.op_type in {"FILTER", "RERANK"}:
        # Multi-parent inputs are concatenated in parent order; a document found by
        # several parents is kept once (first occurrence wins).
        merged: Dict[str, Candidate] = {}
        for candidate in target.inputs:
            merged.setdefault(candidate.candidate_id, candidate)
        return _renumber(list(merged.values()))
    if target.op_type in {"GATE", "TRANSFORM"}:
        return _renumber(target.outputs)
    return None


def _project_descendants(
    trace: RetrievalTrace,
    target: OperatorSpan,
    replacement: List[Candidate] | None,
) -> Dict[str, List[Candidate]]:
    """Counterfactual outputs for every descendant whose inputs changed.

    Strict rule, applied per span in topological order:
    * FUSE: reciprocal-rank fusion is recomputed exactly over its arms, with the
      removed arm dropped (producer) or substituted (replacement).
    * SOURCE: untouched. A source's outputs do not derive from parent candidates;
      the edge is a control dependency (e.g. a gate).
    * anything else: its recorded outputs are filtered to the documents that still
      flow in. If any counterfactual input was never observed by the span, its
      decision on that document is unknown and the replay is indeterminate.
    """
    by_id = {span.op_id: span for span in trace.spans}
    descendant_ids = {span.op_id for span in _descendant_spans(trace, target.op_id)}
    surviving_ops = {span.op_id for span in trace.spans if span.op_id != target.op_id}
    cf: Dict[str, List[Candidate]] = {}

    for span in _topological_order(trace):
        if span.op_id not in descendant_ids or span.status != "FIRED":
            continue
        changed_inputs: Dict[str, List[Candidate]] = {}
        unchanged_inputs: Dict[str, List[Candidate]] = {}
        for parent_id in span.parent_ids:
            if parent_id == target.op_id:
                changed_inputs[parent_id] = list(replacement or ())
            elif parent_id in cf:
                changed_inputs[parent_id] = cf[parent_id]
            else:
                recorded = span.input_groups.get(parent_id)
                unchanged_inputs[parent_id] = list(recorded if recorded else by_id[parent_id].outputs)
        if not changed_inputs or span.op_type == "SOURCE":
            continue

        if span.op_type == "FUSE":
            arms = [
                changed_inputs[parent_id] if parent_id in changed_inputs else unchanged_inputs[parent_id]
                for parent_id in span.parent_ids
                if not (parent_id == target.op_id and replacement is None)
            ]
            arms = [arm for arm in arms if arm]
            cf[span.op_id] = (
                _rrf_merge(arms, k=_rrf_k(span), observed_outputs=span.outputs) if arms else []
            )
            continue

        incoming = {c.doc_id for candidates in changed_inputs.values() for c in candidates}
        observed = {c.doc_id for candidates in span.input_groups.values() for c in candidates}
        unseen = incoming - observed
        if unseen:
            raise _Indeterminate(
                f"child '{span.op_id}' never observed {len(unseen)} of the counterfactual "
                "inputs; its decision on them is unknown"
            )
        allowed = incoming | {c.doc_id for candidates in unchanged_inputs.values() for c in candidates}
        kept = [
            c for c in span.outputs
            if c.doc_id in allowed
            # Introduced by this span itself (e.g. an expansion); reused as observed.
            or tuple(c.origin_op_ids) == (span.op_id,)
            # Producer removal: a document another surviving arm also found stays.
            or (replacement is None and bool((set(c.origin_op_ids) - {span.op_id}) & surviving_ops))
        ]
        cf[span.op_id] = _renumber(kept)
    return cf


def without_operator(trace: RetrievalTrace, op_id: str) -> RetrievalTrace:
    """Project the recorded trace as if ``op_id`` had not run.

    Raises `_Indeterminate` (a `ValueError`) when the projection would require
    guessing a downstream operator's decision on documents it never observed.
    Use `simulate_without_operator` for the typed, non-raising result.
    """
    target = next((span for span in trace.spans if span.op_id == op_id), None)
    if target is None:
        raise ValueError(f"Operator '{op_id}' not found in trace")

    counterfactual_outputs = _project_descendants(trace, target, _replacement_for(target))

    spans: List[OperatorSpan] = []
    for span in trace.spans:
        if span.op_id == op_id:
            continue
        projected_parents: List[str] = []
        for parent_id in span.parent_ids:
            if parent_id == op_id:
                projected_parents.extend(target.parent_ids)
            else:
                projected_parents.append(parent_id)
        projected_parents = list(dict.fromkeys(projected_parents))
        if span.op_id in counterfactual_outputs:
            spans.append(_clone_span(span, outputs=counterfactual_outputs[span.op_id], parent_ids=projected_parents))
        else:
            spans.append(_clone_span(span, parent_ids=projected_parents))

    remaining_ids = {span.op_id for span in spans}
    # A removed final operator hands its terminal role to its parents, exactly as
    # its children inherit them above.
    final_op_ids = tuple(dict.fromkeys(
        final_id
        for declared in trace.final_op_ids
        for final_id in (target.parent_ids if declared == op_id else (declared,))
        if final_id in remaining_ids
    ))
    if not final_op_ids and spans:
        parent_ids = {parent_id for span in spans for parent_id in span.parent_ids}
        sinks = [span.op_id for span in spans if span.op_id not in parent_ids]
        final_op_ids = tuple(sinks)
    metadata = dict(trace.metadata)
    metadata["replay_timing"] = "unavailable: recorded operators were not re-executed"

    return RetrievalTrace(
        trace_id=f"{trace.trace_id}:without:{op_id}",
        service_id=trace.service_id,
        run_id=trace.run_id,
        query_id=trace.query_id,
        query_text=trace.query_text,
        pipeline_id=trace.pipeline_id,
        spans=spans,
        status=trace.status,
        timestamp=trace.timestamp,
        dataset_id=trace.dataset_id,
        corpus_version=trace.corpus_version,
        index_version=trace.index_version,
        request_id=trace.request_id,
        capture=trace.capture,
        metadata=metadata,
        error_traceback=trace.error_traceback,
        final_op_ids=final_op_ids,
        schema_version=trace.schema_version,
    )


def simulate_without_operator(trace: RetrievalTrace, op_id: str) -> ReplayResult:
    """Return an honest recorded-output replay result for removing ``op_id``.

    ``NOT_REPLAYABLE`` on the target or any fired descendant makes the result
    indeterminate, as does any projection that would need a descendant's decision
    on documents it never observed. Callers must not compute deltas, intervals, or
    significance from an indeterminate result.
    """
    assumptions = replay_assumptions(trace, op_id)
    target = next(span for span in trace.spans if span.op_id == op_id)
    unsupported_descendants = [
        span.op_id
        for span in _descendant_spans(trace, op_id)
        if span.status == "FIRED" and span.replay_policy == "NOT_REPLAYABLE"
    ]
    if target.replay_policy == "NOT_REPLAYABLE":
        return ReplayResult(
            op_id=op_id,
            status="indeterminate",
            evidence_class="unavailable",
            trace=None,
            assumptions=assumptions,
            reason=f"Operator '{op_id}' declares replay_policy=NOT_REPLAYABLE.",
            unsupported_descendants=unsupported_descendants,
        )
    if unsupported_descendants:
        return ReplayResult(
            op_id=op_id,
            status="indeterminate",
            evidence_class="unavailable",
            trace=None,
            assumptions=assumptions,
            reason="Removing the operator would change descendants that cannot be replayed.",
            unsupported_descendants=unsupported_descendants,
        )
    try:
        projected = without_operator(trace, op_id)
    except _Indeterminate as exc:
        return ReplayResult(
            op_id=op_id,
            status="indeterminate",
            evidence_class="unavailable",
            trace=None,
            assumptions=assumptions,
            reason=exc.reason,
            unsupported_descendants=unsupported_descendants,
        )
    return ReplayResult(
        op_id=op_id,
        status="replayed",
        evidence_class="replayed",
        trace=projected,
        assumptions=assumptions,
    )


async def attribute_miss(
    trace: RetrievalTrace,
    qrels: Dict[str, Dict[str, int] | List[str] | set[str]],
    k: int = 10,
    edge_store=None,
) -> List[MissAttribution]:
    relevant = qrels.get(trace.query_id) or {}
    rel_set = set(relevant.keys()) if isinstance(relevant, dict) else set(relevant)
    if not rel_set:
        return []
    final_span = _find_final_span(trace)
    final_doc_ids = set(c.doc_id for c in (final_span.outputs[:k] if final_span else []))
    misses = sorted(rel_set - final_doc_ids)
    if not misses:
        return []

    all_by_stage = [set(c.doc_id for c in span.outputs) for span in trace.spans]
    children_of: Dict[str, Set[str]] = {}
    for span in trace.spans:
        for pid in span.parent_ids:
            children_of.setdefault(pid, set()).add(span.op_id)
    # Only a fired operator on the path to the final output can drop a document;
    # a skipped branch made no decision and a dead branch's decision never lands.
    by_id = {span.op_id: span for span in trace.spans}
    final_path_ids: Set[str] = set()
    frontier = list(trace.final_op_ids) if trace.final_op_ids else ([final_span.op_id] if final_span else [])
    while frontier:
        current = frontier.pop()
        if current in final_path_ids or current not in by_id:
            continue
        final_path_ids.add(current)
        frontier.extend(by_id[current].parent_ids)

    def _descendant_ids(root_op_id: str) -> Set[str]:
        seen: Set[str] = set()
        frontier = [root_op_id]
        while frontier:
            current = frontier.pop()
            for child in children_of.get(current, set()):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return seen

    attributions: List[MissAttribution] = []
    for miss in misses:
        found_stage = next((idx for idx, docs in enumerate(all_by_stage) if miss in docs), None)
        if found_stage is None:
            if edge_store is not None and trace.spans:
                retrieved = [c.doc_id for c in trace.spans[0].outputs]
                try:
                    reachable = await edge_store.gold_reachable_via_edge(retrieved, miss)
                except Exception:
                    reachable = False
                if reachable:
                    attributions.append(
                        MissAttribution(
                            query_id=trace.query_id,
                            doc_id=miss,
                            miss_type="gate_blocked",
                            op_id=None,
                            confidence="hypothesis",
                            note="Gold doc is graph-reachable from retrieved set",
                        )
                    )
                    continue
            attributions.append(
                MissAttribution(
                    query_id=trace.query_id,
                    doc_id=miss,
                    miss_type="never_retrieved",
                    op_id=None,
                    confidence="high",
                )
            )
            continue
        dropped_at = None
        descendant_ids = _descendant_ids(trace.spans[found_stage].op_id)
        for idx in range(found_stage + 1, len(all_by_stage)):
            candidate_span = trace.spans[idx]
            if candidate_span.op_id not in descendant_ids:
                continue
            if candidate_span.status != "FIRED" or candidate_span.op_id not in final_path_ids:
                continue
            if miss not in all_by_stage[idx]:
                dropped_at = idx
                break
        if dropped_at is not None:
            dropping_span = trace.spans[dropped_at]
            miss_type = _MISS_TYPE_BY_OP_TYPE.get(dropping_span.op_type, "dropped_by_op")
            attributions.append(
                MissAttribution(
                    query_id=trace.query_id,
                    doc_id=miss,
                    miss_type=miss_type,
                    op_id=dropping_span.op_id,
                    confidence="high",
                )
            )
            continue
        if miss in final_doc_ids:
            continue
        attributions.append(
            MissAttribution(
                query_id=trace.query_id,
                doc_id=miss,
                miss_type="ranked_below_k",
                op_id=None,
                confidence="high",
                note=f"Present in span outputs but not in top-{k} final results",
            )
        )
    return attributions
