from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Dict, List, Sequence

from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2


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


def without_operator(trace: RetrievalTraceV2, op_id: str) -> RetrievalTraceV2:
    target = next((span for span in trace.spans if span.op_id == op_id), None)
    if target is None:
        raise ValueError(f"Operator '{op_id}' not found in trace")

    spans: List[OperatorSpan] = []
    removed_output_doc_ids: set[str] = set()
    replacement_output: List[Candidate] | None = None
    if target.op_type == "BOOST":
        restored: List[Candidate] = []
        for candidate in target.outputs:
            pre = candidate.score_components.get("pre_boost")
            if pre is None:
                continue
            restored.append(
                Candidate(
                    doc_id=candidate.doc_id,
                    score=float(pre),
                    rank=candidate.rank,
                    origin_op_ids=list(candidate.origin_op_ids),
                    score_components=dict(candidate.score_components),
                    add_reason=candidate.add_reason,
                    drop_reason=candidate.drop_reason,
                    metadata=dict(candidate.metadata),
                )
            )
        replacement_output = sorted(restored, key=lambda c: c.score, reverse=True)
        for idx, candidate in enumerate(replacement_output, start=1):
            candidate.rank = idx
    elif target.op_type == "EXPAND":
        replacement_output = [
            c for c in target.outputs if not (len(c.origin_op_ids) == 1 and c.origin_op_ids[0] == target.op_id)
        ]
    elif target.op_type == "FILTER":
        replacement_output = list(target.inputs)
    elif target.op_type == "RERANK":
        replacement_output = list(target.inputs)
    elif target.op_type in {"GATE", "TRANSFORM"}:
        replacement_output = list(target.outputs)
    else:
        removed_output_doc_ids = {c.doc_id for c in target.outputs}

    propagated = False
    for span in trace.spans:
        if span.op_id == op_id:
            continue
        outputs = list(span.outputs)
        if replacement_output is not None and not propagated:
            outputs = list(replacement_output)
            propagated = True
        elif removed_output_doc_ids:
            outputs = [candidate for candidate in outputs if candidate.doc_id not in removed_output_doc_ids]
        spans.append(_clone_span(span, outputs=outputs))

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
    )


def attribute_miss(
    trace: RetrievalTraceV2,
    qrels: Dict[str, Dict[str, int] | List[str] | set[str]],
    k: int = 10,
    edge_store=None,
) -> List[MissAttribution]:
    relevant = qrels.get(trace.query_id) or {}
    rel_set = set(relevant.keys()) if isinstance(relevant, dict) else set(relevant)
    if not rel_set:
        return []
    final_doc_ids = set(c.doc_id for c in (trace.spans[-1].outputs[:k] if trace.spans else []))
    misses = sorted(rel_set - final_doc_ids)
    if not misses:
        return []

    all_by_stage = [set(c.doc_id for c in span.outputs) for span in trace.spans]
    attributions: List[MissAttribution] = []
    for miss in misses:
        found_stage = next((idx for idx, docs in enumerate(all_by_stage) if miss in docs), None)
        if found_stage is None:
            if edge_store is not None and trace.spans:
                retrieved = [c.doc_id for c in trace.spans[0].outputs]
                try:
                    maybe_reachable = edge_store.gold_reachable_via_edge(retrieved, miss)
                    if inspect.isawaitable(maybe_reachable):
                        reachable = False
                    else:
                        reachable = bool(maybe_reachable)
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
        for idx in range(found_stage + 1, len(all_by_stage)):
            if miss not in all_by_stage[idx]:
                dropped_at = idx
                break
        if dropped_at is None:
            attributions.append(
                MissAttribution(
                    query_id=trace.query_id,
                    doc_id=miss,
                    miss_type="unreachable",
                    op_id=trace.spans[found_stage].op_id if trace.spans else None,
                    confidence="hypothesis",
                )
            )
            continue
        attributions.append(
            MissAttribution(
                query_id=trace.query_id,
                doc_id=miss,
                miss_type="dropped_by_op",
                op_id=trace.spans[dropped_at].op_id,
                confidence="high",
            )
        )
    return attributions
