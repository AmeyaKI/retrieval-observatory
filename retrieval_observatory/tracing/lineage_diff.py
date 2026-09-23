from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from retrieval_observatory.release.readiness import ClaimReadiness, ReadinessStatus
from retrieval_observatory.tracing.lineage import CandidateLineageGraph, CandidatePassport

if TYPE_CHECKING:  # runtime import stays inside _journey_index: evidence.service imports this module
    from retrieval_observatory.evidence.investigation import JourneyRow


LineageChangeKind = Literal[
    "newly_surfaced",
    "newly_dropped",
    "newly_retained",
    "rank_shifted",
    "branch_changed",
    "exit_changed",
]


@dataclass(frozen=True)
class CandidateLineageChange:
    kind: LineageChangeKind
    logical_chunk_id: str
    document_identity: str
    baseline_candidate_id: str | None
    candidate_candidate_id: str | None
    detail: str


@dataclass(frozen=True)
class CandidateLineageDiff:
    status: ReadinessStatus
    reasons: tuple[str, ...]
    baseline: CandidateLineageGraph
    candidate: CandidateLineageGraph
    changed: tuple[CandidateLineageChange, ...]


def _document_identity(passport: CandidatePassport) -> str | None:
    return passport.source.document_revision or passport.source.content_hash


def _identity(passport: CandidatePassport) -> tuple[str, str] | None:
    document_identity = _document_identity(passport)
    if passport.logical_chunk_id is None or document_identity is None:
        return None
    return passport.logical_chunk_id, document_identity


def _rank(passport: CandidatePassport) -> int | None:
    ranks = [route.stages[-1].rank for route in passport.routes if route.stages]
    return min(ranks) if ranks else None


def _branches(passport: CandidatePassport) -> tuple[str, ...]:
    return tuple(sorted({branch for route in passport.routes for branch in route.branch_ids}))


def _exit(passport: CandidatePassport) -> tuple[str | None, str | None, str | None]:
    return passport.removed_at, passport.removal_branch_id, passport.removal_reason


def _index(
    graph: CandidateLineageGraph,
) -> tuple[dict[tuple[str, str], CandidatePassport], list[str]]:
    result: dict[tuple[str, str], CandidatePassport] = {}
    reasons: list[str] = []
    for passport in graph.candidates.values():
        identity = _identity(passport)
        if identity is None:
            reasons.append(
                f"candidate {passport.candidate_id} lacks logical chunk and document revision/content hash identity"
            )
            continue
        if identity in result:
            reasons.append(f"candidate identity {identity[0]} at {identity[1]} is not unique")
            continue
        result[identity] = passport
    return result, reasons


def _revision_mismatches(
    baseline: CandidateLineageGraph,
    candidate: CandidateLineageGraph,
) -> list[str]:
    def revisions(graph: CandidateLineageGraph) -> dict[str, set[str]]:
        values: dict[str, set[str]] = {}
        for passport in graph.candidates.values():
            if passport.logical_chunk_id and _document_identity(passport):
                values.setdefault(passport.logical_chunk_id, set()).add(_document_identity(passport) or "")
        return values

    baseline_revisions = revisions(baseline)
    candidate_revisions = revisions(candidate)
    return [
        f"document revision/content hash differs for logical chunk {logical_chunk_id}"
        for logical_chunk_id in sorted(baseline_revisions.keys() & candidate_revisions.keys())
        if baseline_revisions[logical_chunk_id] != candidate_revisions[logical_chunk_id]
    ]


def diff_candidate_lineage(
    baseline: CandidateLineageGraph,
    candidate: CandidateLineageGraph,
    *,
    readiness: ClaimReadiness,
) -> CandidateLineageDiff:
    """Compare observed candidate paths only when query, topology, and stable identity align."""
    reasons = [finding.detail for finding in readiness.findings]
    alignment_reasons: list[str] = []
    if baseline.query_id != candidate.query_id:
        alignment_reasons.append("Baseline and candidate query IDs are not aligned.")
    if baseline.pipeline_id != candidate.pipeline_id:
        alignment_reasons.append("Baseline and candidate pipeline IDs are not aligned.")
    baseline_index, baseline_identity_reasons = _index(baseline)
    candidate_index, candidate_identity_reasons = _index(candidate)
    alignment_reasons.extend(baseline_identity_reasons)
    alignment_reasons.extend(candidate_identity_reasons)
    alignment_reasons.extend(_revision_mismatches(baseline, candidate))
    reasons.extend(alignment_reasons)
    reasons = list(dict.fromkeys(reasons))

    if readiness.status == "BLOCK" or alignment_reasons:
        return CandidateLineageDiff("BLOCK", tuple(reasons), baseline, candidate, ())
    if readiness.status == "HOLD":
        return CandidateLineageDiff("HOLD", tuple(reasons or ["Lineage alignment evidence is inconclusive."]), baseline, candidate, ())

    changes: list[CandidateLineageChange] = []
    all_identities = sorted(baseline_index.keys() | candidate_index.keys())
    for logical_chunk_id, document_identity in all_identities:
        identity = (logical_chunk_id, document_identity)
        before = baseline_index.get(identity)
        after = candidate_index.get(identity)
        common = {
            "logical_chunk_id": logical_chunk_id,
            "document_identity": document_identity,
            "baseline_candidate_id": before.candidate_id if before else None,
            "candidate_candidate_id": after.candidate_id if after else None,
        }
        if before is None and after is not None:
            changes.append(CandidateLineageChange("newly_surfaced", **common, detail="Candidate is observed only in the candidate run."))
            continue
        if before is not None and after is None:
            changes.append(CandidateLineageChange("newly_dropped", **common, detail="Candidate is observed only in the baseline run."))
            continue
        assert before is not None and after is not None

        if _exit(before) != _exit(after):
            changes.append(CandidateLineageChange("exit_changed", **common, detail=f"Recorded exit changed from {_exit(before)} to {_exit(after)}."))
        if before.final_context_member and not after.final_context_member:
            changes.append(CandidateLineageChange("newly_dropped", **common, detail="Candidate left the final context in the candidate run."))
        elif not before.final_context_member and after.final_context_member:
            changes.append(CandidateLineageChange("newly_retained", **common, detail="Candidate entered the final context in the candidate run."))
        if _rank(before) != _rank(after):
            changes.append(CandidateLineageChange("rank_shifted", **common, detail=f"Observed terminal rank changed from {_rank(before)} to {_rank(after)}."))
        if _branches(before) != _branches(after):
            changes.append(CandidateLineageChange("branch_changed", **common, detail=f"Observed branches changed from {_branches(before)} to {_branches(after)}."))

    return CandidateLineageDiff("READY", (), baseline, candidate, tuple(changes))


# ---------------------------------------------------------------------------
# Journey-based diff: two runs' journey rows joined on (query, namespace, unit, entity),
# never on display text. Every change is a recorded fact about final membership, rank or
# the recorded exit path; nothing here asserts why it changed.
# ---------------------------------------------------------------------------

ChangeKind = Literal["lost", "gained", "membership_changed", "rank_changed", "path_changed", "unchanged", "unaligned"]
Alignment = Literal[
    "aligned",
    "query_unaligned",
    "entity_revision_changed",
    "missing_in_baseline",
    "missing_in_candidate",
    "corpus_changed",
]

CHANGE_PRIORITY: dict[str, int] = {
    "lost": 0,
    "gained": 1,
    "membership_changed": 2,
    "rank_changed": 3,
    "path_changed": 4,
    "unaligned": 5,
    "unchanged": 6,
}
_UNALIGNED_DETAIL = {
    "query_unaligned": "query input differs between the runs; no change classification",
    "missing_in_baseline": "query has no rows in the baseline run; no change classification",
    "missing_in_candidate": "query has no rows in the candidate run; no change classification",
}
_NOT_OBSERVED = ("excluded", None, "not_observed", "complete")


@dataclass(frozen=True)
class JourneySide:
    trace_id: str
    outcome: str
    final_membership: str
    in_final_output: bool | None
    final_rank: int | None
    loss_boundary: str | None
    capture_state: str
    judgment: str
    grade: int | None
    events_summary: tuple[str, ...]
    investigation_link: str


@dataclass(frozen=True)
class JourneyDiffRow:
    query_id: str
    namespace: str
    entity_id: str
    unit: str
    alignment: Alignment
    change: ChangeKind
    detail: str
    baseline: JourneySide | None
    candidate: JourneySide | None
    capture_limited: bool
    priority: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for side in ("baseline", "candidate"):
            if payload[side] is not None:
                payload[side]["events_summary"] = list(payload[side]["events_summary"])
        return payload


@dataclass(frozen=True)
class StageAlignment:
    matched: tuple[tuple[str, str], ...]
    baseline_only: tuple[str, ...]
    candidate_only: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": [list(pair) for pair in self.matched],
            "baseline_only": list(self.baseline_only),
            "candidate_only": list(self.candidate_only),
        }


def align_stages(baseline_stages: Sequence[Mapping[str, Any]], candidate_stages: Sequence[Mapping[str, Any]]) -> StageAlignment:
    """Pair stages by ``operator_id`` (``op_id`` fallback); repeated invocations pair in order."""

    def by_operator(stages: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for stage in stages:
            groups.setdefault(str(stage.get("operator_id") or stage["op_id"]), []).append(str(stage["op_id"]))
        return groups

    baseline, candidate = by_operator(baseline_stages), by_operator(candidate_stages)
    matched: list[tuple[str, str]] = []
    baseline_only: list[str] = []
    candidate_only: list[str] = []
    for operator_id, ops in baseline.items():
        other = candidate.get(operator_id, [])
        matched.extend(zip(ops, other))
        baseline_only.extend(ops[len(other):])
        candidate_only.extend(other[len(ops):])
    candidate_only.extend(op for operator_id, ops in candidate.items() if operator_id not in baseline for op in ops)
    order = {str(stage["op_id"]): index for index, stage in enumerate(candidate_stages)}
    return StageAlignment(tuple(matched), tuple(baseline_only), tuple(sorted(candidate_only, key=order.__getitem__)))


def _journey_index(rows: Sequence[Any]) -> dict[tuple[str, str, str, str], JourneyRow]:
    from retrieval_observatory.evidence.investigation import JourneyRow

    index: dict[tuple[str, str, str, str], JourneyRow] = {}
    for row in rows:
        row = row if isinstance(row, JourneyRow) else JourneyRow.from_dict(row)
        index.setdefault((row.query_id, row.namespace, row.unit, row.entity_id), row)  # first trace of a query wins
    return index


def _side(row: JourneyRow | None) -> JourneySide | None:
    if row is None:
        return None
    return JourneySide(
        trace_id=row.trace_id,
        outcome=row.outcome,
        final_membership=row.final_membership,
        in_final_output=row.in_final_output,
        final_rank=row.final_rank,
        loss_boundary=row.loss_boundary,
        capture_state=row.capture_state,
        judgment=row.judgment,
        grade=row.grade,
        events_summary=tuple(f"{event.op_id}:{event.kind}" for event in row.events),
        investigation_link=row.investigation_link,
    )


def _state(row: JourneyRow | None) -> tuple[str, int | None, str | None, str]:
    """(membership, final rank, loss boundary, capture state); a missing row is an unobserved entity."""
    if row is None:
        return _NOT_OBSERVED
    return row.final_membership, row.final_rank, row.loss_boundary, row.capture_state


def _describe(membership: str, rank: int | None, boundary: str | None) -> str:
    if membership == "unknown":
        return "membership unknown (final boundary not fully captured)"
    where = f" at rank {rank}" if rank is not None else ""
    return f"included{where}" if membership == "included" else f"excluded{where} ({boundary or 'exit unrecorded'})"


def _change(before: JourneyRow | None, after: JourneyRow | None, *, membership_only: bool = False) -> tuple[ChangeKind, str]:
    b_membership, b_rank, b_boundary, b_capture = _state(before)
    a_membership, a_rank, a_boundary, a_capture = _state(after)
    detail = f"{_describe(b_membership, b_rank, b_boundary)} → {_describe(a_membership, a_rank, a_boundary)}"
    if b_membership == "unknown" or a_membership == "unknown":
        return ("unchanged" if b_membership == a_membership else "membership_changed"), detail
    if b_membership != a_membership:
        return ("lost" if b_membership == "included" else "gained"), detail
    if membership_only:
        return "unchanged", detail
    if b_membership == "included":
        return ("rank_changed" if b_rank != a_rank else "unchanged"), detail
    if b_boundary != a_boundary or b_capture != a_capture:
        return "path_changed", detail
    return "unchanged", detail


def diff_journeys(
    baseline_rows: Sequence[Any],
    candidate_rows: Sequence[Any],
    *,
    query_alignment: Mapping[str, Alignment],
    corpus_changed: bool = False,
) -> list[JourneyDiffRow]:
    """One row per (query, namespace, unit, entity) seen on either side, final-outcome changes first.

    ``query_alignment`` maps query ids to ``aligned``/``query_unaligned`` (stable query input identity, computed
    by the caller); a query with rows on one side only is ``missing_in_*``. Unaligned queries and a changed corpus
    keep both sides but carry no change classification.
    """
    baseline, candidate = _journey_index(baseline_rows), _journey_index(candidate_rows)
    baseline_queries = {key[0] for key in baseline}
    candidate_queries = {key[0] for key in candidate}
    rows: list[JourneyDiffRow] = []
    for key in baseline.keys() | candidate.keys():
        query_id, namespace, unit, entity_id = key
        before, after = baseline.get(key), candidate.get(key)
        limited = any(row is not None and (row.final_membership == "unknown" or row.capture_state == "partial") for row in (before, after))

        def build(alignment: Alignment, change: ChangeKind, detail: str) -> JourneyDiffRow:
            return JourneyDiffRow(query_id, namespace, entity_id, unit, alignment, change, detail, _side(before), _side(after), limited, CHANGE_PRIORITY[change])

        state = query_alignment.get(query_id, "aligned")
        if state == "aligned" and query_id not in baseline_queries:
            state = "missing_in_baseline"
        elif state == "aligned" and query_id not in candidate_queries:
            state = "missing_in_candidate"
        if corpus_changed:
            rows.append(build("corpus_changed", "unaligned", "corpus identity differs between the runs; entities are not matched"))
        elif state != "aligned":
            rows.append(build(state, "unaligned", _UNALIGNED_DETAIL[state]))
        elif before is None or after is None:
            missing = "baseline" if before is None else "candidate"
            change, detail = _change(before, after)
            rows.append(build(f"missing_in_{missing}", change, f"{detail}; entity has no row in the {missing} run"))
        elif before.entity_revision is not None and after.entity_revision is not None and before.entity_revision != after.entity_revision:
            change, detail = _change(before, after, membership_only=True)
            rows.append(
                build(
                    "entity_revision_changed",
                    change,
                    f"entity revision changed ({before.entity_revision} → {after.entity_revision}); {detail}; exact chunk diff unavailable",
                )
            )
        else:
            rows.append(build("aligned", *_change(before, after)))
    rows.sort(key=lambda row: (row.priority, row.query_id, row.namespace, row.entity_id))
    return rows


def summarize_journey_diff(rows: Sequence[JourneyDiffRow]) -> dict[str, Any]:
    return {
        "pairs": len({(row.query_id, row.namespace, row.unit, row.entity_id) for row in rows}),
        "by_change": {**dict.fromkeys(CHANGE_PRIORITY, 0), **Counter(row.change for row in rows)},
        "by_alignment": dict(Counter(row.alignment for row in rows)),
        "capture_limited": sum(row.capture_limited for row in rows),
    }


__all__ = [
    "Alignment",
    "CHANGE_PRIORITY",
    "CandidateLineageChange",
    "CandidateLineageDiff",
    "ChangeKind",
    "JourneyDiffRow",
    "JourneySide",
    "LineageChangeKind",
    "StageAlignment",
    "align_stages",
    "diff_candidate_lineage",
    "diff_journeys",
    "summarize_journey_diff",
]
