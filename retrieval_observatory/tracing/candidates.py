from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from retrieval_observatory.tracing.model import Candidate


@dataclass(frozen=True)
class CandidateTransition:
    input_groups: dict[str, tuple[Candidate, ...]]
    outputs: tuple[Candidate, ...]

    @property
    def inputs(self) -> tuple[Candidate, ...]:
        return tuple(candidate for candidates in self.input_groups.values() for candidate in candidates)

    def __iter__(self):
        # Temporary internal convenience while execution consumers move to the
        # canonical grouped fields in Phase B.
        yield list(self.inputs)
        yield list(self.outputs)


_DROP_REASON_BY_OP_TYPE = {
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

_ADD_REASON_BY_OP_TYPE = {
    "SOURCE": "retrieved",
    "FUSE": "fused",
    "EXPAND": "expanded",
    "TRANSFORM": "transformed",
    "BOOST": "boosted",
}


def clone_candidate(candidate: Candidate) -> Candidate:
    return replace(
        candidate,
        origin_op_ids=tuple(candidate.origin_op_ids),
        score_components=dict(candidate.score_components),
        metadata=dict(candidate.metadata),
        parent_candidate_ids=tuple(candidate.parent_candidate_ids),
    )


@dataclass(frozen=True)
class _CandidateFields:
    doc_id: str
    score: float
    rank: int
    metadata: Dict[str, Any]
    candidate_id: str | None = None
    logical_chunk_id: str | None = None
    document_id: str | None = None
    document_revision: str | None = None
    content_hash: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    parent_candidate_ids: tuple[str, ...] = ()
    identity_evidence: str | None = None
    decision_reason: str | None = None
    decision_evidence: str | None = None
    add_reason: str | None = None


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _item_fields(item: Any, index: int) -> _CandidateFields:
    if isinstance(item, str):
        return _CandidateFields(item, 0.0, index, {})
    metadata = dict(_item_value(item, "metadata", {}) or {})
    observed_doc_id = _item_value(item, "doc_id") or _item_value(item, "id") or metadata.get("id")
    doc_id = str(observed_doc_id or index)
    return _CandidateFields(
        doc_id=doc_id,
        score=float(_item_value(item, "score", 0.0)),
        rank=int(_item_value(item, "rank", index)),
        metadata=metadata,
        candidate_id=_item_value(item, "candidate_id"),
        logical_chunk_id=_item_value(item, "logical_chunk_id"),
        document_id=_item_value(item, "document_id"),
        document_revision=_item_value(item, "document_revision"),
        content_hash=_item_value(item, "content_hash"),
        char_start=_item_value(item, "char_start"),
        char_end=_item_value(item, "char_end"),
        parent_candidate_ids=tuple(_item_value(item, "parent_candidate_ids", ()) or ()),
        identity_evidence=_item_value(item, "identity_evidence") or ("partial" if not observed_doc_id else None),
        decision_reason=_item_value(item, "decision_reason"),
        decision_evidence=_item_value(item, "decision_evidence"),
        add_reason=_item_value(item, "add_reason"),
    )


def to_candidates(value: Any, op_id: str) -> List[Candidate]:
    if not isinstance(value, (list, tuple)):
        return []
    candidates: List[Candidate] = []
    for index, item in enumerate(value, start=1):
        fields = _item_fields(item, index)
        candidates.append(
            Candidate(
                doc_id=fields.doc_id,
                score=fields.score,
                rank=fields.rank,
                output_rank=fields.rank,
                origin_op_ids=(op_id,),
                metadata=fields.metadata,
                candidate_id=fields.candidate_id,
                logical_chunk_id=fields.logical_chunk_id,
                document_id=fields.document_id,
                document_revision=fields.document_revision,
                content_hash=fields.content_hash,
                char_start=fields.char_start,
                char_end=fields.char_end,
                parent_candidate_ids=fields.parent_candidate_ids,
                identity_evidence=fields.identity_evidence or "recorded",
                decision_reason=fields.decision_reason,
                decision_evidence=fields.decision_evidence or "unavailable",
            )
        )
    return candidates


def build_candidate_transition(
    *,
    input_groups: Mapping[str, Sequence[Candidate]],
    output_items: Iterable[Any],
    op_id: str,
    op_type: str,
    decision_reasons: Mapping[str, str] | None = None,
) -> CandidateTransition:
    """Build an immutable before/after candidate transition for one operator."""
    output_rows = [_item_fields(item, index) for index, item in enumerate(output_items, start=1)]
    decision_reasons = decision_reasons or {}
    known_input_ids = {candidate.candidate_id for candidates in input_groups.values() for candidate in candidates}

    def output_rank(candidate: Candidate) -> int | None:
        for row in output_rows:
            if row.candidate_id == candidate.candidate_id:
                return row.rank
            if candidate.candidate_id in row.parent_candidate_ids:
                return row.rank
        for row in output_rows:
            identity_is_unmatched = row.candidate_id is None or row.candidate_id not in known_input_ids
            if identity_is_unmatched and not row.parent_candidate_ids and row.doc_id == candidate.doc_id:
                return row.rank
        return None

    normalized_groups: Dict[str, List[Candidate]] = {}
    inputs_by_doc: Dict[str, List[tuple[str, Candidate]]] = {}
    inputs_by_id: Dict[str, List[tuple[str, Candidate]]] = {}
    for parent_id, candidates in input_groups.items():
        normalized_groups[parent_id] = []
        for candidate in candidates:
            copied = clone_candidate(candidate)
            copied.input_rank = candidate.output_rank if candidate.output_rank is not None else candidate.rank
            copied.output_rank = output_rank(candidate)
            copied.drop_reason = None
            copied.metadata["last_op_id"] = parent_id
            if copied.output_rank is None:
                recorded_reason = decision_reasons.get(candidate.candidate_id) or decision_reasons.get(candidate.doc_id)
                copied.drop_reason = recorded_reason or _DROP_REASON_BY_OP_TYPE.get(op_type, "unknown")
                copied.decision_reason = recorded_reason
                copied.decision_evidence = "recorded" if recorded_reason is not None else "legacy_inferred"
            normalized_groups[parent_id].append(copied)
            inputs_by_doc.setdefault(candidate.doc_id, []).append((parent_id, candidate))
            inputs_by_id.setdefault(candidate.candidate_id, []).append((parent_id, candidate))

    outputs: List[Candidate] = []
    for row in output_rows:
        if row.parent_candidate_ids:
            matches = [
                match
                for parent_candidate_id in row.parent_candidate_ids
                for match in inputs_by_id.get(parent_candidate_id, ())
            ]
        elif row.candidate_id is not None:
            matches = inputs_by_id.get(row.candidate_id, [])
            if not matches:
                matches = inputs_by_doc.get(row.doc_id, [])
        else:
            matches = inputs_by_doc.get(row.doc_id, [])
        origins: List[str] = []
        for _, candidate in matches:
            for origin in candidate.origin_op_ids:
                if origin not in origins:
                    origins.append(origin)
        if not origins:
            origins = [op_id]

        input_rank = min(
            (
                candidate.output_rank if candidate.output_rank is not None else candidate.rank
                for _, candidate in matches
            ),
            default=None,
        )
        score_components: Dict[str, float] = {}
        if op_type == "FUSE":
            for parent_id, candidate in matches:
                score_components[parent_id] = candidate.score
        elif len(matches) == 1:
            score_components = dict(matches[0][1].score_components)

        source_candidate_ids = tuple(dict.fromkeys(candidate.candidate_id for _, candidate in matches))
        parent_candidate_ids = row.parent_candidate_ids or source_candidate_ids
        candidate_id = row.candidate_id or (source_candidate_ids[0] if len(source_candidate_ids) == 1 else row.doc_id)
        logical_chunk_ids = {candidate.logical_chunk_id for _, candidate in matches}
        logical_chunk_id = row.logical_chunk_id or (logical_chunk_ids.pop() if len(logical_chunk_ids) == 1 else row.doc_id)
        source = matches[0][1] if matches else None
        previous_add_reason = source.add_reason if source else None
        add_reason = row.add_reason or _ADD_REASON_BY_OP_TYPE.get(op_type) or previous_add_reason or "transformed"
        outputs.append(
            Candidate(
                doc_id=row.doc_id,
                score=row.score,
                rank=row.rank,
                input_rank=input_rank,
                output_rank=row.rank,
                origin_op_ids=origins,
                score_components=score_components,
                add_reason=add_reason,
                metadata={**row.metadata, "last_op_id": op_id},
                candidate_id=candidate_id,
                logical_chunk_id=logical_chunk_id,
                document_id=row.document_id or (source.document_id if source else None),
                document_revision=row.document_revision or (source.document_revision if source else None),
                content_hash=row.content_hash or (source.content_hash if source else None),
                char_start=row.char_start if row.char_start is not None else source.char_start if source else None,
                char_end=row.char_end if row.char_end is not None else source.char_end if source else None,
                parent_candidate_ids=parent_candidate_ids,
                identity_evidence=row.identity_evidence or ("partial" if len(matches) > 1 and row.candidate_id is None else "recorded"),
                decision_reason=row.decision_reason,
                decision_evidence=(row.decision_evidence or "recorded") if row.decision_reason else "unavailable",
            )
        )

    return CandidateTransition(
        input_groups={parent: tuple(candidates) for parent, candidates in normalized_groups.items()},
        outputs=tuple(outputs),
    )
