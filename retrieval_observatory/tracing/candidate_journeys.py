"""Compatibility rows for the Query-detail miss table, derived from ``project_trace_journeys``.

Row keys are unchanged; the values come from recorded boundaries only. Counterfactual miss
attribution is gone, so ``miss_type`` is always ``None``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from retrieval_observatory.datasets.judgments import EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence.investigation import JourneyRow
from retrieval_observatory.evidence.journeys import project_trace_journeys
from retrieval_observatory.tracing.candidate_history import _DROP_REASON_BY_OP_TYPE
from retrieval_observatory.tracing.model import RetrievalTrace

_LEGACY_OUTCOME = {
    "relevant_delivered": "relevant_retained",
    "retained_below_cutoff": "relevant_retained",
    "relevant_excluded": "relevant_dropped_at_stage",
    "not_observed": "relevant_lost_upstream",
    "unjudged": "unknown_relevance",
    "insufficient_evidence": "lineage_incomplete",
}


def _doc_preview(trace: RetrievalTrace, doc_id: str) -> Optional[str]:
    for span in trace.spans:
        for cand in list(span.outputs) + list(span.inputs):
            if cand.doc_id != doc_id:
                continue
            meta = cand.metadata or {}
            for key in ("preview", "text", "title", "snippet"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    return text if len(text) <= 160 else text[:157] + "..."
    return None


def _judgments(trace: RetrievalTrace, query_id: str, qrels_for_query: Mapping[str, int]) -> JudgmentSet:
    """Legacy qrels carry no namespace: judge every namespace the trace observed."""
    namespaces = sorted(
        {c.metadata.get("namespace") or "default" for span in trace.spans for c in (*span.inputs, *span.outputs)}
    ) or ["default"]
    qrels = {query_id: dict(qrels_for_query)}
    return JudgmentSet(j for namespace in namespaces for j in JudgmentSet.from_qrels(qrels, namespace=namespace))


def _row(trace: RetrievalTrace, row: JourneyRow, query_text: Optional[str]) -> Dict[str, Any]:
    relevant = row.judgment == "relevant"
    survived = bool(row.in_final_output)
    dropped_at = row.loss_boundary if not survived and row.loss_boundary not in {None, "unknown", "not_observed"} else None
    drop_reason: Optional[str] = None
    drop_inferred = False
    if dropped_at is not None:
        removal = next(e for e in reversed(row.events) if e.op_id == dropped_at and e.kind == "removed")
        drop_reason, drop_inferred = removal.reason, removal.reason_evidence != "recorded"
        if drop_reason is None:
            drop_reason = _DROP_REASON_BY_OP_TYPE.get(str(trace.span(dropped_at).op_type), "unknown")
    if row.outcome == "judged_nonrelevant":
        outcome = "irrelevant_retained" if survived else "irrelevant_removed"
    else:
        outcome = _LEGACY_OUTCOME[row.outcome]
    if row.final_membership == "unknown":
        outcome_evidence = "unavailable"
    else:
        outcome_evidence = "recorded" if row.capture_state == "complete" else "partial"
    return {
        "query_id": row.query_id,
        "query_text": query_text,
        "doc_id": row.entity_id,
        "doc_preview": _doc_preview(trace, row.entity_id),
        "pipeline_id": trace.pipeline_id,
        "trace_id": trace.trace_id,
        "relevant": relevant,
        "grade": row.grade if relevant else None,
        "survived": survived,
        "final_rank": row.final_rank,
        "introduced_at": next((e.op_id for e in row.events if e.kind in {"introduced", "recovered"}), None),
        "dropped_at": dropped_at,
        "drop_reason": drop_reason,
        "drop_reason_inferred": drop_inferred,
        "miss_type": None,
        "outcome": outcome,
        "outcome_evidence": outcome_evidence,
        "evidence_class": "unavailable" if drop_reason is None else "inferred" if drop_inferred else "measured",
    }


async def build_candidate_journeys(
    traces: List[RetrievalTrace],
    *,
    query_id: str,
    query_text: Optional[str],
    qrels_for_query: Mapping[str, int],
    k: int = 10,
    qrel_chunk_mapping_complete: bool = False,
) -> List[Dict[str, Any]]:
    """Return evidence-aware compatibility rows for observed and qrel candidates."""
    spec = EvaluationSpec(unit="document", k=k)
    rows: List[Dict[str, Any]] = []
    for trace in traces:
        if trace.query_id != query_id:
            continue
        unobserved: set[str] = set()
        for row in project_trace_journeys(trace, _judgments(trace, query_id, qrels_for_query), spec):
            if not row.observed:
                if row.entity_id in unobserved:
                    continue
                unobserved.add(row.entity_id)
            rows.append(_row(trace, row, query_text))

    def _sort_key(row: Dict[str, Any]) -> tuple:
        # Relevant + dropped first, then relevant survivors, then other drops.
        relevant = 0 if row["relevant"] else 1
        dropped = 0 if (row["dropped_at"] and not row["survived"]) else 1
        return (relevant, dropped, row["pipeline_id"], row["doc_id"])

    rows.sort(key=_sort_key)
    return rows
