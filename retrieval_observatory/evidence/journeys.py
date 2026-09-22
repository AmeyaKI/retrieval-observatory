"""Project recorded operator boundaries into journey rows. Pure functions, no I/O.

One ``JourneyEvent`` per (FIRED invocation, candidate id) and one ``JourneyRow`` per
(query, evaluation entity at ``spec.unit``). Everything here is descriptive: a ``removed``
event is a candidate present in an input group and absent from a completely captured output;
an ``unknown`` event is the same observation across an incomplete boundary, and no reason is
asserted for it. Membership at the final boundary, judgment and capture completeness stay
separate fields (``docs/rebuild/EVIDENCE_CONTRACT.md``).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Sequence
from urllib.parse import quote

from retrieval_observatory.datasets.judgments import (
    ChunkMap,
    EntityRef,
    EvaluationSpec,
    EvaluationUnit,
    JudgmentSet,
    canonical_json,
    confusion_cell,
    resolve_relevance,
)
from retrieval_observatory.evidence.investigation import (
    DERIVATION_VERSION,
    JOURNEY_SCHEMA_VERSION,
    JourneyEvent,
    JourneyRow,
    Outcome,
)
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

_PRIORITY: dict[Outcome, int] = {
    "relevant_excluded": 0,
    "not_observed": 0,
    "insufficient_evidence": 1,
    "relevant_delivered": 2,
    "retained_below_cutoff": 3,
    "judged_nonrelevant": 4,
    "unjudged": 5,
}
_STAGE_FIELDS = ("queries_served", "queries_skipped", "candidates_received", "removal_events", "introduced", "partial_boundaries")


def entity_of_candidate(candidate: Candidate, unit: EvaluationUnit) -> EntityRef:
    namespace = candidate.metadata.get("namespace") or "default"
    if unit == "chunk":
        return EntityRef(namespace, str(candidate.logical_chunk_id), "chunk", candidate.document_revision)
    return EntityRef(namespace, str(candidate.document_id or candidate.doc_id), "document", candidate.document_revision)


def trace_digest(trace: RetrievalTrace) -> str:
    payload = trace.to_dict()
    payload.pop("timestamp", None)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _output_complete(span: OperatorSpan) -> bool:
    return span.output_capture == "recorded" and (span.params.get("capture") or {}).get("outputs") != "truncated"


def _boundary_complete(span: OperatorSpan) -> bool:
    return _output_complete(span) and span.input_capture != "unavailable"


def _span_events(span: OperatorSpan, removed_before: set[str]) -> list[tuple[Candidate, JourneyEvent]]:
    """One event per candidate id in a FIRED span's input groups or outputs, inputs first."""
    inputs: dict[str, list[Candidate]] = {}
    for candidates in span.input_groups.values():
        for candidate in candidates:
            inputs.setdefault(str(candidate.candidate_id), []).append(candidate)
    outputs = {str(candidate.candidate_id): candidate for candidate in span.outputs}
    children: dict[str, list[Candidate]] = {}
    for candidate in span.outputs:
        for parent_id in candidate.parent_candidate_ids:
            children.setdefault(parent_id, []).append(candidate)
    complete = _boundary_complete(span)

    events: list[tuple[Candidate, JourneyEvent]] = []
    for candidate_id in {**inputs, **outputs}:
        occurrences = inputs.get(candidate_id, [])
        output = outputs.get(candidate_id)
        derived = children.get(candidate_id, []) if output is None else []
        input_rank = min((c.input_rank if c.input_rank is not None else c.rank for c in occurrences), default=None)
        output_rank = output.rank if output is not None else min((c.rank for c in derived), default=None)
        reason: str | None = None
        evidence = "recorded"
        if output is not None and not occurrences:
            kind = "recovered" if candidate_id in removed_before else "introduced"
            reason = output.add_reason
        elif output is not None:
            kind = "retained" if output_rank == input_rank else "promoted" if output_rank < input_rank else "demoted"
            if len(occurrences) > 1:
                reason = "deduplicated"
        elif derived:
            kind = "transformed"
        elif not complete:
            kind, evidence = "unknown", "unavailable"
        else:
            kind = "removed"
            removed_before.add(candidate_id)
            recorded = next((c.decision_reason for c in occurrences if c.decision_reason), None)
            inferred = next((c.drop_reason for c in occurrences if c.decision_evidence == "legacy_inferred" and c.drop_reason), None)
            if recorded:
                reason = recorded
            elif inferred:
                reason, evidence = inferred, "inferred"
            else:
                evidence = "unavailable"
        candidate = output or occurrences[0]
        events.append(
            (
                candidate,
                JourneyEvent(
                    op_id=span.op_id,
                    operator_id=str(span.operator_id),
                    invocation_id=span.invocation_id,
                    branch=span.branch_id,
                    occurrence_entity_id=str(candidate.logical_chunk_id),
                    candidate_id=candidate_id,
                    kind=kind,
                    input_present=bool(occurrences),
                    output_present=output is not None or bool(derived),
                    input_rank=input_rank,
                    output_rank=output_rank,
                    input_occurrences=len(occurrences),
                    reason=reason,
                    reason_evidence=evidence,
                    boundary_complete=complete,
                    input_evidence=span.input_capture,
                    source_occurrences=tuple(output.parent_candidate_ids) if output is not None else (),
                ),
            )
        )
    return events


def _trace_events(trace: RetrievalTrace) -> list[tuple[OperatorSpan, Candidate, JourneyEvent]]:
    removed: set[str] = set()
    events: list[tuple[OperatorSpan, Candidate, JourneyEvent]] = []
    for span in trace.spans:
        if span.status == "FIRED":
            events.extend((span, candidate, event) for candidate, event in _span_events(span, removed))
    return events


def _final_op_ids(trace: RetrievalTrace) -> tuple[str, ...]:
    if trace.final_op_ids:
        return trace.final_op_ids
    parents = {parent for span in trace.spans for parent in span.parent_ids}
    return tuple(span.op_id for span in trace.spans if span.op_id not in parents)


def _on_final_path(trace: RetrievalTrace, final_ops: Sequence[str]) -> set[str]:
    by_id = {span.op_id: span for span in trace.spans}
    on_path: set[str] = set()
    frontier = list(final_ops)
    while frontier:
        op_id = frontier.pop()
        if op_id not in on_path:
            on_path.add(op_id)
            frontier.extend(by_id[op_id].parent_ids)
    return on_path


def _entities(candidate: Candidate, spec: EvaluationSpec, chunk_map: ChunkMap | None) -> tuple[EntityRef, EntityRef]:
    """(row entity, entity to resolve the judgment with) for one occurrence."""
    entity = entity_of_candidate(candidate, spec.unit)
    if spec.unit == "document" and candidate.document_id is None and chunk_map is not None:
        chunk = entity_of_candidate(candidate, "chunk")
        mapped = chunk_map.document_for(chunk)
        return (replace(mapped, revision=candidate.document_revision) if mapped is not None else entity), chunk
    return entity, entity


@dataclass
class _Group:
    entity: EntityRef
    judged_as: EntityRef
    events: list[JourneyEvent] = field(default_factory=list)
    final_ranks: list[tuple[str, int]] = field(default_factory=list)


def _link(trace: RetrievalTrace, entity: EntityRef) -> str:
    return (
        f"#/investigate?run={quote(str(trace.run_id or ''))}&pipeline={quote(trace.pipeline_id)}"
        f"&view=queries&query={quote(trace.query_id)}&trace={quote(trace.trace_id)}"
        f"&entity={quote(f'{entity.namespace}:{entity.entity_id}')}"
    )


def project_trace_journeys(
    trace: RetrievalTrace,
    judgments: JudgmentSet,
    spec: EvaluationSpec,
    *,
    chunk_map: ChunkMap | None = None,
) -> list[JourneyRow]:
    final_ops = _final_op_ids(trace)
    on_path = _on_final_path(trace, final_ops)
    final_complete = all(_output_complete(trace.span(op_id)) for op_id in final_ops)
    failure_ops = {str(failure.get("op_id")) for failure in trace.capture_failures}
    trace_flags = trace.capture.lineage_evidence in {"partial", "unavailable"} or trace.capture.candidates_truncated
    # A trace-level flag with no span-level marker cannot be localised, so it taints every row.
    unlocalised = trace_flags and all(_boundary_complete(span) for span in trace.spans if span.status == "FIRED")
    sources_complete = all(_output_complete(span) for span in trace.spans if span.op_type == "SOURCE")

    groups: dict[tuple[str, str, str], _Group] = {}
    for span, candidate, event in _trace_events(trace):
        entity, judged_as = _entities(candidate, spec, chunk_map)
        group = groups.setdefault(entity.key(), _Group(entity, judged_as))
        group.events.append(event)
        if span.op_id in final_ops and event.output_present and event.kind != "transformed" and event.output_rank is not None:
            group.final_ranks.append((span.op_id, event.output_rank))
    for entity in judgments.relevant_entities(trace.query_id, spec):
        groups.setdefault(entity.key(), _Group(entity, entity))

    rows: list[JourneyRow] = []
    for group in groups.values():
        events = tuple(group.events)
        observed = bool(events)
        relevance, grade, basis = resolve_relevance(judgments, trace.query_id, group.judged_as, spec, chunk_map)
        judgment = "unmapped" if basis == "unmapped" else relevance
        record = judgments.get(trace.query_id, group.entity) if grade is not None else None
        source = None if record is None else record.source.kind + (f"@{record.source.version}" if record.source.version else "")

        final_rank = min((rank for _, rank in group.final_ranks), default=None)
        if not final_complete:
            membership, in_final = "unknown", None
        else:
            in_final = final_rank is not None
            membership = "included" if in_final and (spec.k is None or final_rank <= spec.k) else "excluded"

        if observed:
            partial = any(not event.boundary_complete for event in events) or bool({e.op_id for e in events} & failure_ops) or unlocalised
        else:
            partial = not sources_complete or bool(trace.capture_failures) or trace_flags

        loss_boundary: str | None = None
        if membership == "included":
            pass
        elif in_final:
            loss_boundary = min(group.final_ranks, key=lambda item: item[1])[0]
        elif not observed:
            loss_boundary = "not_observed"
        else:
            for event in events:
                if event.op_id in on_path and event.kind in {"removed", "unknown"}:
                    loss_boundary = event.op_id if event.kind == "removed" else "unknown"

        outcome: Outcome
        if membership == "unknown":
            outcome = "insufficient_evidence"
        elif relevance == "relevant":
            if membership == "included":
                outcome = "relevant_delivered"
            elif in_final:
                outcome = "retained_below_cutoff"
            elif loss_boundary == "unknown" or (not observed and partial):
                outcome = "insufficient_evidence"
            elif not observed:
                outcome = "not_observed"
            else:
                outcome = "relevant_excluded"
        elif relevance == "nonrelevant":
            outcome = "judged_nonrelevant"
        else:
            outcome = "unjudged"

        rows.append(
            JourneyRow(
                schema_version=JOURNEY_SCHEMA_VERSION,
                derivation_version=DERIVATION_VERSION,
                run_id=trace.run_id,
                pipeline_id=trace.pipeline_id,
                trace_id=trace.trace_id,
                query_id=trace.query_id,
                namespace=group.entity.namespace,
                entity_id=group.entity.entity_id,
                unit=spec.unit,
                entity_revision=group.entity.revision,
                judgment=judgment,
                grade=grade,
                judgment_source=source,
                final_membership=membership,
                in_final_output=in_final,
                final_rank=final_rank,
                outcome=outcome,
                confusion=confusion_cell(relevance, None if membership == "unknown" else membership == "included"),
                capture_state="partial" if partial else "complete",
                observed=observed,
                loss_boundary=loss_boundary,
                priority=1 if outcome == "relevant_excluded" and partial else _PRIORITY[outcome],
                events=events,
                occurrence_entity_ids=tuple(dict.fromkeys(event.occurrence_entity_id for event in events))
                or ((group.entity.entity_id,) if spec.unit == "chunk" else ()),
                evaluation_digest=spec.digest(),
                judgment_digest=judgments.digest(),
                trace_digest=trace_digest(trace),
                investigation_link=_link(trace, group.entity),
            )
        )
    rows.sort(key=lambda row: (row.priority, row.namespace, row.entity_id))
    return rows


def summarize_journeys(rows: Sequence[JourneyRow]) -> dict[str, Any]:
    """Counts over unique (query, entity) pairs; an entity that exits twice is still one pair."""
    by_query: dict[str, dict[str, int]] = {}
    by_entity: dict[str, dict[str, int]] = {}
    for row in rows:
        query = by_query.setdefault(row.query_id, dict.fromkeys(("pairs", "TP", "FP", "FN", "TN", "unknown", "relevant_excluded"), 0))
        query["pairs"] += 1
        query[row.confusion] += 1
        query["relevant_excluded"] += row.outcome == "relevant_excluded"
        entity = by_entity.setdefault(f"{row.namespace}:{row.entity_id}", dict.fromkeys(("queries", "delivered", "excluded", "not_observed", "unknown"), 0))
        entity["queries"] += 1
        entity["delivered"] += row.outcome == "relevant_delivered"
        entity["excluded"] += row.final_membership == "excluded"
        entity["not_observed"] += row.outcome == "not_observed"
        entity["unknown"] += row.outcome == "insufficient_evidence"
    relevant = [row for row in rows if row.judgment == "relevant"]
    return {
        "pairs": len(rows),
        "events": sum(len(row.events) for row in rows),
        "by_outcome": dict(Counter(row.outcome for row in rows)),
        "by_confusion": dict(Counter(row.confusion for row in rows)),
        "relevant_final_misses_observed_upstream": sum(row.final_membership == "excluded" and row.observed for row in relevant),
        "relevant_final_misses_never_observed": sum(not row.observed for row in relevant),
        "unknown_capture": sum(row.outcome == "insufficient_evidence" for row in rows),
        "by_loss_boundary": dict(Counter(row.loss_boundary for row in rows if row.loss_boundary is not None)),
        "by_query": by_query,
        "by_entity": by_entity,
    }


def summarize_stages(traces: Sequence[RetrievalTrace]) -> dict[str, Any]:
    """Per operator node: invocations served/skipped, candidates received, introductions, removals, partial boundaries."""
    by_op_id: dict[str, dict[str, int]] = {}
    operator_of: dict[str, str] = {}
    for trace in traces:
        for span in trace.spans:
            operator_of[span.op_id] = str(span.operator_id)
            counts = by_op_id.setdefault(span.op_id, dict.fromkeys(_STAGE_FIELDS, 0))
            counts["queries_skipped"] += span.status == "SKIPPED_BY_GATE"
            if span.status != "FIRED":
                continue
            counts["queries_served"] += 1
            counts["candidates_received"] += sum(len(group) for group in span.input_groups.values())
            counts["partial_boundaries"] += not _boundary_complete(span)
        for span, _, event in _trace_events(trace):
            by_op_id[span.op_id]["introduced"] += event.kind in {"introduced", "recovered"}
            by_op_id[span.op_id]["removal_events"] += event.kind == "removed"
    by_operator_id: dict[str, dict[str, int]] = {}
    for op_id, counts in by_op_id.items():
        aggregate = by_operator_id.setdefault(operator_of[op_id], dict.fromkeys(_STAGE_FIELDS, 0))
        for key, value in counts.items():
            aggregate[key] += value
    return {"by_op_id": by_op_id, "by_operator_id": by_operator_id}
