"""Bulk candidate-journey rows for the Query-detail miss table."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from retrieval_observatory.tracing.candidate_history import candidate_history
from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.tracing.replay import MissAttribution, attribute_miss


def _doc_ids_seen(trace: RetrievalTrace) -> Set[str]:
    ids: Set[str] = set()
    for span in trace.spans:
        for cand in span.outputs:
            ids.add(cand.doc_id)
        for cand in span.inputs:
            ids.add(cand.doc_id)
    return ids


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


def _miss_index(misses: Iterable[MissAttribution]) -> Dict[str, MissAttribution]:
    return {m.doc_id: m for m in misses}


def _evidence_class(
    *,
    history_dropped_reason: Optional[str],
    drop_reason_inferred: bool,
    miss: Optional[MissAttribution],
) -> str:
    if miss is not None and miss.confidence == "hypothesis":
        return "inferred"
    if history_dropped_reason and drop_reason_inferred:
        return "inferred"
    if history_dropped_reason or (miss is not None and miss.miss_type):
        return "measured"
    return "unavailable"


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
    relevant_ids = {doc_id for doc_id, grade in qrels_for_query.items() if grade > 0}
    rows: List[Dict[str, Any]] = []

    for trace in traces:
        if trace.query_id != query_id:
            continue
        seen = _doc_ids_seen(trace)
        graph = build_candidate_lineage(
            trace,
            qrels_for_query=qrels_for_query,
            qrel_chunk_mapping_complete=qrel_chunk_mapping_complete,
        )
        # Docs of interest: all relevant + any seen doc (we'll keep rows that are
        # relevant or that were dropped in this pipeline).
        candidates = set(relevant_ids) | seen
        misses = await attribute_miss(trace, qrels={query_id: dict(qrels_for_query)}, k=k)
        by_miss = _miss_index(misses)

        for doc_id in sorted(candidates):
            history = candidate_history(trace, doc_id)
            relevant = doc_id in relevant_ids
            grade = int(qrels_for_query.get(doc_id, 0)) if relevant else None
            if history.introduced_at is None and not relevant:
                continue

            passport = next(
                (
                    value
                    for value in graph.candidates.values()
                    if value.candidate_id == doc_id
                    or value.logical_chunk_id == doc_id
                    or value.source.document_id == doc_id
                ),
                None,
            )
            if passport is not None:
                outcome = passport.outcome.kind
                outcome_evidence = passport.outcome.evidence
            elif relevant and graph.qrel_chunk_mapping_complete and graph.retrieval_entry_complete:
                outcome = "relevant_lost_upstream"
                outcome_evidence = "recorded"
            else:
                outcome = "lineage_incomplete"
                outcome_evidence = "partial"

            drop_inferred = False
            if history.events:
                for event in reversed(history.events):
                    if event.event == "dropped":
                        drop_inferred = bool(event.drop_reason_inferred)
                        break

            miss = by_miss.get(doc_id) if relevant and not history.survived else None
            # Relevant docs that survived still appear in the table (outcome=survived).
            if relevant and history.survived:
                miss = None

            rows.append(
                {
                    "query_id": query_id,
                    "query_text": query_text,
                    "doc_id": doc_id,
                    "doc_preview": _doc_preview(trace, doc_id),
                    "pipeline_id": trace.pipeline_id,
                    "trace_id": trace.trace_id,
                    "relevant": relevant,
                    "grade": grade if relevant else None,
                    "survived": history.survived,
                    "final_rank": history.final_rank,
                    "introduced_at": history.introduced_at,
                    "dropped_at": history.dropped_at if not history.survived else None,
                    "drop_reason": history.dropped_reason if not history.survived else None,
                    "drop_reason_inferred": drop_inferred if not history.survived else False,
                    "miss_type": miss.miss_type if miss is not None else None,
                    "outcome": outcome,
                    "outcome_evidence": outcome_evidence,
                    "evidence_class": _evidence_class(
                        history_dropped_reason=history.dropped_reason if not history.survived else None,
                        drop_reason_inferred=drop_inferred,
                        miss=miss,
                    ),
                }
            )

    def _sort_key(row: Dict[str, Any]) -> tuple:
        # Relevant + dropped first, then relevant survivors, then other drops.
        relevant = 0 if row["relevant"] else 1
        dropped = 0 if (row["dropped_at"] and not row["survived"]) else 1
        return (relevant, dropped, row["pipeline_id"], row["doc_id"])

    rows.sort(key=_sort_key)
    return rows
