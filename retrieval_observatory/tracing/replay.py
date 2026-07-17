from __future__ import annotations

from dataclasses import dataclass, field
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
        rrf_k = int(fuse_child.params.get("k", 60))
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


def _rrf_merge(arm_outputs: List[List[Candidate]], k: int = 60) -> List[Candidate]:
    """Reciprocal rank fusion across multiple arms."""
    scores: Dict[str, float] = {}
    origins: Dict[str, List[str]] = {}
    components: Dict[str, Dict[str, float]] = {}
    candidate_map: Dict[str, Candidate] = {}
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
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result: List[Candidate] = []
    for rank_pos, (doc_id, score) in enumerate(ranked, start=1):
        base = candidate_map[doc_id]
        result.append(Candidate(
            doc_id=doc_id,
            score=score,
            rank=rank_pos,
            origin_op_ids=sorted(set(origins.get(doc_id, []))),
            score_components=components.get(doc_id, {}),
            add_reason="fused",
            metadata=dict(base.metadata),
        ))
    return result


def without_operator(trace: RetrievalTrace, op_id: str) -> RetrievalTrace:
    target = next((span for span in trace.spans if span.op_id == op_id), None)
    if target is None:
        raise ValueError(f"Operator '{op_id}' not found in trace")

    children_of: Dict[str, Set[str]] = {}
    for span in trace.spans:
        for pid in span.parent_ids:
            children_of.setdefault(pid, set()).add(span.op_id)

    fuse_child = None
    if target.op_type == "SOURCE":
        for span in trace.spans:
            if span.op_type == "FUSE" and op_id in span.parent_ids:
                fuse_child = span
                break

    replacement_output: List[Candidate] | None = None
    removed_output_doc_ids: set[str] = set()

    if target.op_type == "BOOST":
        restored: List[Candidate] = []
        for candidate in target.outputs:
            pre = candidate.score_components.get("pre_boost")
            if pre is None:
                continue
            restored.append(Candidate(
                doc_id=candidate.doc_id,
                score=float(pre),
                rank=candidate.rank,
                origin_op_ids=list(candidate.origin_op_ids),
                score_components=dict(candidate.score_components),
                add_reason=candidate.add_reason,
                drop_reason=candidate.drop_reason,
                metadata=dict(candidate.metadata),
            ))
        replacement_output = sorted(restored, key=lambda c: c.score, reverse=True)
        for idx, candidate in enumerate(replacement_output, start=1):
            candidate.rank = idx
    elif target.op_type == "EXPAND":
        replacement_output = [
            c for c in target.outputs
            if not (len(c.origin_op_ids) == 1 and c.origin_op_ids[0] == target.op_id)
            and c.add_reason != "expanded"
        ]
    elif target.op_type == "FILTER":
        replacement_output = list(target.inputs)
    elif target.op_type == "RERANK":
        replacement_output = list(target.inputs)
    elif target.op_type in {"GATE", "TRANSFORM"}:
        replacement_output = list(target.outputs)
    elif target.op_type == "SOURCE" and fuse_child is not None:
        pass
    else:
        removed_output_doc_ids = {c.doc_id for c in target.outputs}

    counterfactual_outputs: Dict[str, List[Candidate]] = {}

    if target.op_type == "SOURCE" and fuse_child is not None:
        remaining_arm_outputs: List[List[Candidate]] = []
        for span in trace.spans:
            if span.op_id != op_id and span.op_id in fuse_child.parent_ids:
                remaining_arm_outputs.append(list(span.outputs))
        rrf_k = fuse_child.params.get("k", 60)
        if remaining_arm_outputs:
            counterfactual_outputs[fuse_child.op_id] = _rrf_merge(remaining_arm_outputs, k=rrf_k)
        else:
            counterfactual_outputs[fuse_child.op_id] = []
    elif replacement_output is not None:
        direct_children = children_of.get(op_id, set())
        for child_id in direct_children:
            counterfactual_outputs[child_id] = list(replacement_output)
        if not direct_children:
            for span in trace.spans:
                if span.op_id == op_id:
                    continue
                idx = trace.spans.index(span)
                target_idx = trace.spans.index(target)
                if idx > target_idx and span.op_id not in counterfactual_outputs:
                    counterfactual_outputs[span.op_id] = list(replacement_output)
                    break

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
            cf_out = counterfactual_outputs[span.op_id]
            spans.append(_clone_span(span, outputs=cf_out, parent_ids=projected_parents))
            cf_doc_ids = {c.doc_id for c in cf_out}
            for downstream_id in children_of.get(span.op_id, set()):
                if downstream_id not in counterfactual_outputs:
                    ds_span = next((s for s in trace.spans if s.op_id == downstream_id), None)
                    if ds_span:
                        filtered = [c for c in ds_span.outputs if c.doc_id in cf_doc_ids]
                        counterfactual_outputs[downstream_id] = filtered
        elif removed_output_doc_ids:
            outputs = [c for c in span.outputs if c.doc_id not in removed_output_doc_ids]
            spans.append(_clone_span(span, outputs=outputs, parent_ids=projected_parents))
        else:
            spans.append(_clone_span(span, parent_ids=projected_parents))

    remaining_ids = {span.op_id for span in spans}
    final_op_ids = tuple(op_id for op_id in trace.final_op_ids if op_id in remaining_ids)
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
    )


def simulate_without_operator(trace: RetrievalTrace, op_id: str) -> ReplayResult:
    """Return an honest recorded-output replay result for removing ``op_id``.

    ``NOT_REPLAYABLE`` on the target or any fired descendant makes the result
    indeterminate. Callers must not compute deltas, intervals, or significance from
    an indeterminate result.
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
    return ReplayResult(
        op_id=op_id,
        status="replayed",
        evidence_class="replayed",
        trace=without_operator(trace, op_id),
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
            if trace.spans[idx].op_id not in descendant_ids:
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
