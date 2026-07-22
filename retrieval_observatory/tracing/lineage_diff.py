from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from retrieval_observatory.release.readiness import ClaimReadiness, ReadinessStatus
from retrieval_observatory.tracing.lineage import CandidateLineageGraph, CandidatePassport


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
    if baseline.topology_hash != candidate.topology_hash:
        alignment_reasons.append("Recorded topology differs; stage-aligned lineage comparison is blocked.")

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


__all__ = [
    "CandidateLineageChange",
    "CandidateLineageDiff",
    "LineageChangeKind",
    "diff_candidate_lineage",
]
