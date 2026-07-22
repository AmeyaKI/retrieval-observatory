from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Mapping

from retrieval_observatory.tracing.lineage_contract import LineageEvidence
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

OutcomeKind = Literal[
    "relevant_retained",
    "irrelevant_removed",
    "irrelevant_retained",
    "relevant_lost_upstream",
    "relevant_dropped_at_stage",
    "unknown_relevance",
    "lineage_incomplete",
]

_EVIDENCE_RANK = {"recorded": 0, "legacy_inferred": 1, "partial": 2, "unavailable": 3}


@dataclass(frozen=True)
class CandidateSource:
    document_id: str | None
    document_revision: str | None
    content_hash: str | None
    char_start: int | None
    char_end: int | None
    preview: str | None


@dataclass(frozen=True)
class CandidateStage:
    op_id: str
    op_type: str
    branch_id: str | None
    rank: int
    score: float
    score_components: Mapping[str, float]


@dataclass(frozen=True)
class CandidateRoute:
    candidate_ids: tuple[str, ...]
    operator_ids: tuple[str, ...]
    branch_ids: tuple[str, ...]
    stages: tuple[CandidateStage, ...]
    lineage_evidence: LineageEvidence


@dataclass(frozen=True)
class RelevanceEvidence:
    kind: Literal["relevant", "irrelevant", "unknown"]
    grade: int | None = None
    evidence: Literal["validated", "unavailable"] = "unavailable"


@dataclass(frozen=True)
class CandidateOutcome:
    kind: OutcomeKind
    evidence: LineageEvidence
    operator_id: str | None = None
    branch_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CandidatePassport:
    candidate_id: str
    logical_chunk_id: str | None
    source: CandidateSource
    parent_candidate_ids: tuple[str, ...]
    routes: tuple[CandidateRoute, ...]
    relevance: RelevanceEvidence
    outcome: CandidateOutcome
    lineage_evidence: LineageEvidence
    final_context_member: bool = False
    removed_at: str | None = None
    removal_branch_id: str | None = None
    removal_reason: str | None = None
    removal_evidence: LineageEvidence = "unavailable"
    derived_child_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateLineageEdge:
    source_candidate_id: str
    target_candidate_id: str
    op_id: str
    evidence: LineageEvidence


@dataclass(frozen=True)
class CandidateLineageGraph:
    trace_id: str
    run_id: str | None
    query_id: str
    pipeline_id: str
    topology_hash: str
    candidates: Mapping[str, CandidatePassport]
    edges: tuple[CandidateLineageEdge, ...]
    qrels_for_query: Mapping[str, int] = field(default_factory=dict)
    qrel_chunk_mapping_complete: bool = False
    retrieval_entry_complete: bool = False
    observed_logical_chunk_ids: tuple[str, ...] = ()


def _worst_evidence(*values: LineageEvidence) -> LineageEvidence:
    return max(values, key=_EVIDENCE_RANK.__getitem__)


def _preview(candidate: Candidate, trace: RetrievalTrace) -> str | None:
    if trace.capture.redacted_field_count or trace.capture.omitted_field_count:
        return None
    for key in ("preview", "text", "title", "snippet"):
        value = candidate.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _branch(span: OperatorSpan) -> str | None:
    value = span.params.get("branch_id")
    return str(value) if value is not None else None


def _relevance(candidate: Candidate, qrels_for_query: Mapping[str, int]) -> RelevanceEvidence:
    logical_chunk_id = candidate.logical_chunk_id
    if (
        candidate.identity_evidence != "recorded"
        or logical_chunk_id is None
        or logical_chunk_id not in qrels_for_query
    ):
        return RelevanceEvidence("unknown")
    grade = int(qrels_for_query[logical_chunk_id])
    return RelevanceEvidence(
        "relevant" if grade > 0 else "irrelevant",
        grade=grade,
        evidence="validated",
    )


def classify_candidate_outcome(passport: CandidatePassport) -> CandidateOutcome:
    if passport.final_context_member:
        if passport.relevance.kind == "relevant":
            return CandidateOutcome("relevant_retained", passport.lineage_evidence)
        if passport.relevance.kind == "irrelevant":
            return CandidateOutcome("irrelevant_retained", passport.lineage_evidence)
        return CandidateOutcome("unknown_relevance", passport.lineage_evidence)

    if passport.removed_at is not None and passport.removal_evidence in {
        "recorded",
        "legacy_inferred",
    }:
        if passport.relevance.kind == "unknown":
            return CandidateOutcome(
                "unknown_relevance",
                passport.removal_evidence,
                operator_id=passport.removed_at,
                branch_id=passport.removal_branch_id,
                reason=passport.removal_reason,
            )
        return CandidateOutcome(
            "relevant_dropped_at_stage"
            if passport.relevance.kind == "relevant"
            else "irrelevant_removed",
            passport.removal_evidence,
            operator_id=passport.removed_at,
            branch_id=passport.removal_branch_id,
            reason=passport.removal_reason,
        )
    return CandidateOutcome(
        "lineage_incomplete",
        "partial" if passport.lineage_evidence != "unavailable" else "unavailable",
        operator_id=passport.removed_at,
        branch_id=passport.removal_branch_id,
        reason="candidate exit or final membership is not fully observed",
    )


def _query_qrels(
    trace: RetrievalTrace,
    qrels_for_query: Mapping[str, int] | None,
    qrels: Mapping[str, Mapping[str, int]] | None,
) -> Mapping[str, int]:
    if qrels_for_query is not None:
        return dict(qrels_for_query)
    if qrels is not None:
        return dict(qrels.get(trace.query_id, {}))
    return {}


def build_candidate_lineage(
    trace: RetrievalTrace,
    *,
    qrels_for_query: Mapping[str, int] | None = None,
    qrel_chunk_mapping_complete: bool = False,
    retrieval_entry_complete: bool | None = None,
    qrels: Mapping[str, Mapping[str, int]] | None = None,
) -> CandidateLineageGraph:
    query_qrels = _query_qrels(trace, qrels_for_query, qrels)
    occurrences: dict[str, list[tuple[OperatorSpan, Candidate, str]]] = {}
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    edges: list[CandidateLineageEdge] = []

    for span in trace.spans:
        for candidates in span.input_groups.values():
            for candidate in candidates:
                occurrences.setdefault(candidate.candidate_id, []).append((span, candidate, "input"))
        for candidate in span.outputs:
            occurrences.setdefault(candidate.candidate_id, []).append((span, candidate, "output"))
            for parent_id in candidate.parent_candidate_ids:
                if parent_id == candidate.candidate_id:
                    continue
                parents.setdefault(candidate.candidate_id, []).append(parent_id)
                children.setdefault(parent_id, []).append(candidate.candidate_id)
                edges.append(
                    CandidateLineageEdge(
                        parent_id,
                        candidate.candidate_id,
                        span.op_id,
                        candidate.identity_evidence,
                    )
                )

    final_ids = {
        candidate.candidate_id
        for span in trace.spans
        if span.op_id in trace.final_op_ids
        for candidate in span.outputs
    }
    trace_partial = bool(
        trace.capture.lineage_evidence in {"partial", "unavailable"}
        or trace.capture.candidates_truncated
        or trace.capture.omitted_field_count
    )
    span_index = {span.op_id: index for index, span in enumerate(trace.spans)}

    def reaches_final(candidate_id: str, visiting: frozenset[str] = frozenset()) -> bool:
        if candidate_id in final_ids:
            return True
        if candidate_id in visiting:
            return False
        return any(
            reaches_final(child_id, visiting | {candidate_id})
            for child_id in children.get(candidate_id, ())
        )

    def routes(candidate_id: str, visiting: frozenset[str] = frozenset()) -> tuple[CandidateRoute, ...]:
        if candidate_id in visiting:
            return ()
        output_occurrences = [
            item for item in occurrences.get(candidate_id, ()) if item[2] == "output"
        ]
        stages = tuple(
            CandidateStage(
                span.op_id,
                str(span.op_type),
                _branch(span),
                candidate.output_rank if candidate.output_rank is not None else candidate.rank,
                candidate.score,
                dict(candidate.score_components),
            )
            for span, candidate, _ in sorted(
                output_occurrences, key=lambda item: span_index[item[0].op_id]
            )
        )
        evidence: LineageEvidence = "recorded"
        for _, candidate, _ in output_occurrences:
            evidence = _worst_evidence(evidence, candidate.identity_evidence)
        if trace_partial:
            evidence = _worst_evidence(evidence, "partial")
        parent_ids = tuple(dict.fromkeys(parents.get(candidate_id, ())))
        if not parent_ids:
            return (
                CandidateRoute(
                    (candidate_id,),
                    tuple(stage.op_id for stage in stages),
                    tuple(stage.branch_id for stage in stages if stage.branch_id is not None),
                    stages,
                    evidence,
                ),
            )
        result = []
        for parent_id in parent_ids:
            parent_routes = routes(parent_id, visiting | {candidate_id}) or (
                CandidateRoute((parent_id,), (), (), (), "partial"),
            )
            for parent_route in parent_routes:
                result.append(
                    CandidateRoute(
                        (*parent_route.candidate_ids, candidate_id),
                        tuple(dict.fromkeys((*parent_route.operator_ids, *(stage.op_id for stage in stages)))),
                        tuple(dict.fromkeys((*parent_route.branch_ids, *(stage.branch_id for stage in stages if stage.branch_id)))),
                        (*parent_route.stages, *stages),
                        _worst_evidence(parent_route.lineage_evidence, evidence),
                    )
                )
        return tuple(result)

    passports: dict[str, CandidatePassport] = {}
    for candidate_id, items in occurrences.items():
        ordered = sorted(items, key=lambda item: span_index[item[0].op_id])
        candidate = next((item[1] for item in ordered if item[2] == "output"), ordered[0][1])
        lineage_evidence = candidate.identity_evidence
        if trace_partial:
            lineage_evidence = _worst_evidence(lineage_evidence, "partial")

        removed_at = None
        removal_branch_id = None
        removal_reason = None
        removal_evidence: LineageEvidence = "unavailable"
        for span, input_candidate, location in ordered:
            if location != "input":
                continue
            output_ids = {output.candidate_id for output in span.outputs}
            transitioned_ids = {
                parent_id for output in span.outputs for parent_id in output.parent_candidate_ids
            }
            if candidate_id in output_ids or candidate_id in transitioned_ids:
                continue
            removed_at = span.op_id
            removal_branch_id = _branch(span)
            removal_reason = input_candidate.decision_reason or input_candidate.drop_reason
            removal_evidence = input_candidate.decision_evidence
            if removal_evidence == "unavailable" and not trace_partial:
                removal_evidence = "legacy_inferred"
                removal_reason = removal_reason or "candidate absent from recorded operator output"
            if removal_evidence not in {"recorded", "legacy_inferred"}:
                lineage_evidence = _worst_evidence(lineage_evidence, "partial")
            break

        route_values = routes(candidate_id)
        for route in route_values:
            lineage_evidence = _worst_evidence(lineage_evidence, route.lineage_evidence)
        passport = CandidatePassport(
            candidate_id=candidate_id,
            logical_chunk_id=candidate.logical_chunk_id,
            source=CandidateSource(
                candidate.document_id
                or (candidate.doc_id if candidate.identity_evidence == "recorded" else None),
                candidate.document_revision,
                candidate.content_hash,
                candidate.char_start,
                candidate.char_end,
                _preview(candidate, trace),
            ),
            parent_candidate_ids=tuple(dict.fromkeys(parents.get(candidate_id, ()))),
            routes=route_values,
            relevance=_relevance(candidate, query_qrels),
            outcome=CandidateOutcome("lineage_incomplete", "unavailable"),
            lineage_evidence=lineage_evidence,
            final_context_member=reaches_final(candidate_id),
            removed_at=removed_at,
            removal_branch_id=removal_branch_id,
            removal_reason=removal_reason,
            removal_evidence=removal_evidence,
            derived_child_ids=tuple(dict.fromkeys(children.get(candidate_id, ()))),
        )
        passports[candidate_id] = replace(passport, outcome=classify_candidate_outcome(passport))

    source_spans = [span for span in trace.spans if span.op_type == "SOURCE"]
    if retrieval_entry_complete is None:
        retrieval_entry_complete = bool(source_spans) and not trace_partial
    return CandidateLineageGraph(
        trace_id=trace.trace_id,
        run_id=trace.run_id,
        query_id=trace.query_id,
        pipeline_id=trace.pipeline_id,
        topology_hash=trace.topology_hash(),
        candidates=passports,
        edges=tuple(dict.fromkeys(edges)),
        qrels_for_query=query_qrels,
        qrel_chunk_mapping_complete=qrel_chunk_mapping_complete,
        retrieval_entry_complete=bool(retrieval_entry_complete),
        observed_logical_chunk_ids=tuple(
            sorted({item.logical_chunk_id for item in passports.values() if item.logical_chunk_id})
        ),
    )
