from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

# When a candidate is present in an operator's inputs but absent from its outputs
# and no explicit drop_reason was recorded, infer the reason from the operator type.
# Inference is honest to what the trace shows; where it is genuinely ambiguous we
# emit "unknown" rather than guessing (Trust principle).
_DROP_REASON_BY_OP_TYPE: Dict[str, str] = {
    "RERANK": "reranked_out",
    "FILTER": "filtered",
    "GATE": "gate_blocked",
    "FUSE": "truncated",
    "BOOST": "truncated",
    "EXPAND": "truncated",
    "SOURCE": "truncated",
    "TRANSFORM": "unknown",
    "GENERATE": "unknown",
}


@dataclass
class CandidateEvent:
    op_id: str
    op_name: str
    op_type: str
    status: str
    event: str  # "introduced" | "passed" | "dropped"
    input_rank: Optional[int] = None
    output_rank: Optional[int] = None
    score: Optional[float] = None
    score_delta: Optional[float] = None
    add_reason: Optional[str] = None
    drop_reason: Optional[str] = None
    drop_reason_inferred: bool = False
    origin_op_ids: List[str] = field(default_factory=list)
    note: str = ""


@dataclass
class CandidateHistory:
    doc_id: str
    trace_id: str
    query_id: str
    introduced_at: Optional[str] = None
    introduced_by_arms: List[str] = field(default_factory=list)
    dropped_at: Optional[str] = None
    dropped_reason: Optional[str] = None
    survived: bool = False
    final_rank: Optional[int] = None
    events: List[CandidateEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        return payload


def _find(candidates: List[Candidate], doc_id: str) -> Optional[Candidate]:
    for c in candidates:
        if c.doc_id == doc_id:
            return c
    return None


def candidate_history(trace: RetrievalTrace, doc_id: str) -> CandidateHistory:
    """Assemble one candidate's full journey through the pipeline.

    Answers the five questions the vision names for Candidate Flow Visualization:
    which document disappeared, where it was removed, why, which reranker promoted
    it, and which retrieval arm found it — using only recorded trace evidence.
    """
    history = CandidateHistory(doc_id=doc_id, trace_id=trace.trace_id, query_id=trace.query_id)
    introduced = False
    last_score: Optional[float] = None
    seen_in_ops: set = set()  # op_ids whose OUTPUTS carried the doc

    for span in trace.spans:
        out_c = _find(span.outputs, doc_id)
        in_c = _find(span.inputs, doc_id)
        # A span "consumes" the doc's stream if it takes input from a span that carried it,
        # or lists it in its own inputs. Topology-based so it works even when inputs are sparse.
        consumes = bool(in_c is not None or (set(span.parent_ids) & seen_in_ops))

        if out_c is not None:
            if not introduced:
                introduced = True
                history.introduced_at = span.op_id
                history.introduced_by_arms = list(out_c.origin_op_ids)
                event = CandidateEvent(
                    op_id=span.op_id,
                    op_name=span.op_name,
                    op_type=str(span.op_type),
                    status=str(span.status),
                    event="introduced",
                    input_rank=out_c.input_rank,
                    output_rank=out_c.output_rank if out_c.output_rank is not None else out_c.rank,
                    score=out_c.score,
                    add_reason=str(out_c.add_reason),
                    origin_op_ids=list(out_c.origin_op_ids),
                    note=f"Introduced by {', '.join(out_c.origin_op_ids) or span.op_name}",
                )
            else:
                delta = None if last_score is None else round(out_c.score - last_score, 6)
                event = CandidateEvent(
                    op_id=span.op_id,
                    op_name=span.op_name,
                    op_type=str(span.op_type),
                    status=str(span.status),
                    event="passed",
                    input_rank=in_c.rank if in_c is not None else out_c.input_rank,
                    output_rank=out_c.output_rank if out_c.output_rank is not None else out_c.rank,
                    score=out_c.score,
                    score_delta=delta,
                    origin_op_ids=list(out_c.origin_op_ids),
                )
            last_score = out_c.score
            seen_in_ops.add(span.op_id)
            history.events.append(event)
        elif introduced and consumes:
            # Present entering this operator, gone from its outputs -> dropped here.
            reason = in_c.drop_reason if in_c is not None else None
            inferred = False
            if reason is None:
                reason = _DROP_REASON_BY_OP_TYPE.get(str(span.op_type), "unknown")
                inferred = True
            history.events.append(
                CandidateEvent(
                    op_id=span.op_id,
                    op_name=span.op_name,
                    op_type=str(span.op_type),
                    status=str(span.status),
                    event="dropped",
                    input_rank=in_c.rank if in_c is not None else None,
                    score=in_c.score if in_c is not None else None,
                    drop_reason=reason,
                    drop_reason_inferred=inferred,
                    note=(
                        "Drop reason not recorded; inferred from operator type"
                        if inferred
                        else "Drop reason recorded on candidate"
                    ),
                )
            )
            history.dropped_at = span.op_id
            history.dropped_reason = reason
            # A dropped candidate can only re-enter via a later source/expand, which
            # would show up as a fresh "introduced" event above; stop tracking here.
            introduced = False
            last_score = None

    final_span = _final_span(trace)
    if final_span is not None:
        final_c = _find(final_span.outputs, doc_id)
        if final_c is not None:
            history.survived = True
            history.final_rank = final_c.output_rank if final_c.output_rank is not None else final_c.rank
            history.dropped_at = None
            history.dropped_reason = None
    return history


def _final_span(trace: RetrievalTrace) -> Optional[OperatorSpan]:
    if trace.final_op_ids:
        for span in trace.spans:
            if span.op_id in trace.final_op_ids:
                return span
    if not trace.spans:
        return None
    all_parent_ids = set()
    for span in trace.spans:
        all_parent_ids.update(span.parent_ids)
    sinks = [s for s in trace.spans if s.op_id not in all_parent_ids]
    if len(sinks) == 1:
        return sinks[0]
    return trace.spans[-1]
