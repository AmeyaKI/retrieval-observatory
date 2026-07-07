from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set

from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2

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


def _clone_span(span: OperatorSpan, *, outputs: Sequence[Candidate] | None = None) -> OperatorSpan:
    return OperatorSpan(
        op_id=span.op_id,
        op_type=span.op_type,
        op_name=span.op_name,
        parent_ids=list(span.parent_ids),
        status=span.status,
        deterministic=span.deterministic,
        replay_policy=span.replay_policy,
        latency_ms=span.latency_ms,
        inputs=list(span.inputs),
        outputs=list(outputs if outputs is not None else span.outputs),
        params=dict(span.params),
        gate_values=dict(span.gate_values),
        input_variant=span.input_variant,
        error=span.error,
    )


def _find_final_span(trace: RetrievalTraceV2) -> Optional[OperatorSpan]:
    """Return the terminal span using final_op_id or sink detection."""
    if trace.final_op_id:
        for span in trace.spans:
            if span.op_id == trace.final_op_id:
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


def without_operator(trace: RetrievalTraceV2, op_id: str) -> RetrievalTraceV2:
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
        if span.op_id in counterfactual_outputs:
            cf_out = counterfactual_outputs[span.op_id]
            spans.append(_clone_span(span, outputs=cf_out))
            cf_doc_ids = {c.doc_id for c in cf_out}
            for downstream_id in children_of.get(span.op_id, set()):
                if downstream_id not in counterfactual_outputs:
                    ds_span = next((s for s in trace.spans if s.op_id == downstream_id), None)
                    if ds_span:
                        filtered = [c for c in ds_span.outputs if c.doc_id in cf_doc_ids]
                        counterfactual_outputs[downstream_id] = filtered
        elif removed_output_doc_ids:
            outputs = [c for c in span.outputs if c.doc_id not in removed_output_doc_ids]
            spans.append(_clone_span(span, outputs=outputs))
        else:
            spans.append(_clone_span(span))

    return RetrievalTraceV2(
        trace_id=f"{trace.trace_id}:without:{op_id}",
        run_id=trace.run_id,
        query_id=trace.query_id,
        query_text=trace.query_text,
        pipeline_id=trace.pipeline_id,
        spans=spans,
        total_latency_ms=trace.total_latency_ms,
        status=trace.status,
        trace_format_version=trace.trace_format_version,
        timestamp=trace.timestamp,
        metadata=dict(trace.metadata),
        error_traceback=trace.error_traceback,
        final_op_id=trace.final_op_id,
    )


async def attribute_miss(
    trace: RetrievalTraceV2,
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
