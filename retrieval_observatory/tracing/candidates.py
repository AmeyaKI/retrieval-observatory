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
    )


def _item_fields(item: Any, index: int) -> tuple[str, float, int, Dict[str, Any]]:
    if isinstance(item, str):
        return item, 0.0, index, {}
    if isinstance(item, dict):
        doc_id = str(item.get("doc_id") or item.get("id", index))
        return (
            doc_id,
            float(item.get("score", 0.0)),
            int(item.get("rank", index)),
            dict(item.get("metadata") or {}),
        )
    doc_id = str(getattr(item, "doc_id", None) or getattr(item, "id", index))
    return (
        doc_id,
        float(getattr(item, "score", 0.0)),
        int(getattr(item, "rank", index)),
        dict(getattr(item, "metadata", {}) or {}),
    )


def to_candidates(value: Any, op_id: str) -> List[Candidate]:
    if not isinstance(value, (list, tuple)):
        return []
    candidates: List[Candidate] = []
    for index, item in enumerate(value, start=1):
        doc_id, score, rank, metadata = _item_fields(item, index)
        candidates.append(
            Candidate(
                doc_id=doc_id,
                score=score,
                rank=rank,
                output_rank=rank,
                origin_op_ids=[op_id],
                metadata=metadata,
            )
        )
    return candidates


def build_candidate_transition(
    *,
    input_groups: Mapping[str, Sequence[Candidate]],
    output_items: Iterable[Any],
    op_id: str,
    op_type: str,
) -> CandidateTransition:
    """Build an immutable before/after candidate transition for one operator."""
    output_rows = [_item_fields(item, index) for index, item in enumerate(output_items, start=1)]
    output_rank_by_id = {doc_id: rank for doc_id, _, rank, _ in output_rows}

    inputs: List[Candidate] = []
    normalized_groups: Dict[str, List[Candidate]] = {}
    inputs_by_doc: Dict[str, List[tuple[str, Candidate]]] = {}
    for parent_id, candidates in input_groups.items():
        normalized_groups[parent_id] = []
        for candidate in candidates:
            copied = clone_candidate(candidate)
            copied.input_rank = candidate.output_rank if candidate.output_rank is not None else candidate.rank
            copied.output_rank = output_rank_by_id.get(candidate.doc_id)
            copied.drop_reason = None
            copied.metadata["last_op_id"] = parent_id
            if copied.output_rank is None:
                copied.drop_reason = _DROP_REASON_BY_OP_TYPE.get(op_type, "unknown")  # type: ignore[assignment]
            inputs.append(copied)
            normalized_groups[parent_id].append(copied)
            inputs_by_doc.setdefault(candidate.doc_id, []).append((parent_id, candidate))

    outputs: List[Candidate] = []
    for doc_id, score, rank, metadata in output_rows:
        matches = inputs_by_doc.get(doc_id, [])
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

        previous_add_reason = matches[0][1].add_reason if matches else None
        add_reason = _ADD_REASON_BY_OP_TYPE.get(op_type) or previous_add_reason or "transformed"
        outputs.append(
            Candidate(
                doc_id=doc_id,
                score=score,
                rank=rank,
                input_rank=input_rank,
                output_rank=rank,
                origin_op_ids=origins,
                score_components=score_components,
                add_reason=add_reason,  # type: ignore[arg-type]
                metadata={**metadata, "last_op_id": op_id},
            )
        )

    return CandidateTransition(
        input_groups={parent: tuple(candidates) for parent, candidates in normalized_groups.items()},
        outputs=tuple(outputs),
    )
