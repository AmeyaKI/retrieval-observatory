from typing import Any, Iterable, Literal


LineageEvidence = Literal["recorded", "legacy_inferred", "partial", "unavailable"]
# How a span's input groups were bound to the invocations that produced them: the producing
# invocation is known from the framework or executor ("recorded"), the decorator/manifest
# declaration was resolved to the latest node of that operator ("declared"), the inputs were
# reconstructed from parent outputs ("inferred"), or inputs exist but no producer link could be
# established ("unavailable").
ParentLinkage = Literal["recorded", "declared", "inferred", "unavailable"]

_LINEAGE_EVIDENCE_VALUES = {"recorded", "legacy_inferred", "partial", "unavailable"}
_PARENT_LINKAGE_VALUES = {"recorded", "declared", "inferred", "unavailable"}
_DERIVED_DECISIONS = {"derived", "expanded", "fused", "transformed"}


def validate_lineage_evidence(value: str, *, field_name: str) -> None:
    if value not in _LINEAGE_EVIDENCE_VALUES:
        raise ValueError(f"{field_name} must be one of {sorted(_LINEAGE_EVIDENCE_VALUES)}")


def validate_parent_linkage(value: str) -> None:
    if value not in _PARENT_LINKAGE_VALUES:
        raise ValueError(f"parent_linkage must be one of {sorted(_PARENT_LINKAGE_VALUES)}")


def validate_candidate_parentage(candidate: Any) -> None:
    if (
        candidate.identity_evidence == "recorded"
        and candidate.decision_evidence == "recorded"
        and candidate.decision_reason in _DERIVED_DECISIONS
        and not candidate.parent_candidate_ids
    ):
        raise ValueError("recorded derived candidate must declare at least one parent candidate ID")


def validate_unique_candidate_ids(candidates: Iterable[Any]) -> None:
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate IDs must be unique within each input/output set")
