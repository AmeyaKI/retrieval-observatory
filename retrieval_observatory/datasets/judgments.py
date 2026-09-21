"""Relevance judgments scoped to (query, evaluation entity).

A judgment is a stored grade for one query and one evaluation entity (a document or a
chunk inside a namespace). Three rules follow from that:

* An absent judgment is absent, never a negative. Unjudged entities are reported as
  ``"unjudged"``, not ``"nonrelevant"``, and confusion counts never count unseen corpus.
* Grades are what is stored; relevance is derived from an ``EvaluationSpec`` threshold.
  An explicit grade of zero is a stored judgment (nonrelevant), distinct from no judgment.
* Entities are identified by (namespace, unit, entity_id). The same local id in two
  namespaces is two entities; a chunk and a document are never the same entity.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Literal, Mapping, Sequence, Tuple

JUDGMENT_SCHEMA_VERSION = 1

EvaluationUnit = Literal["document", "chunk"]
Relevance = Literal["relevant", "nonrelevant", "unjudged"]
ConflictRule = Literal["error", "max", "first", "last"]
ConfusionCell = Literal["TP", "FP", "FN", "TN", "unknown"]


@dataclass(frozen=True)
class EntityRef:
    """One evaluation entity. ``revision`` is descriptive and excluded from identity."""

    namespace: str
    entity_id: str
    unit: EvaluationUnit
    revision: str | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.namespace, self.unit, self.entity_id)

    def to_dict(self) -> dict:
        return {"namespace": self.namespace, "entity_id": self.entity_id, "unit": self.unit, "revision": self.revision}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EntityRef:
        return cls(
            namespace=str(value.get("namespace", "default")),
            entity_id=str(value["entity_id"]),
            unit=value.get("unit", "document"),
            revision=None if value.get("revision") is None else str(value["revision"]),
        )


@dataclass(frozen=True)
class JudgmentSource:
    kind: str
    version: str | None = None


@dataclass(frozen=True)
class Judgment:
    query_id: str
    entity: EntityRef
    grade: int
    source: JudgmentSource
    evidence_span: tuple[int, int] | None = None

    def to_record(self) -> dict:
        return {
            "query_id": self.query_id,
            "namespace": self.entity.namespace,
            "entity_id": self.entity.entity_id,
            "unit": self.entity.unit,
            "revision": self.entity.revision,
            "grade": self.grade,
            "source_kind": self.source.kind,
            "source_version": self.source.version,
            "evidence_span": None if self.evidence_span is None else list(self.evidence_span),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Judgment:
        span = record.get("evidence_span")
        return cls(
            query_id=str(record["query_id"]),
            entity=EntityRef.from_dict(record),
            grade=int(record["grade"]),
            source=JudgmentSource(
                kind=str(record.get("source_kind") or "imported"),
                version=None if record.get("source_version") is None else str(record["source_version"]),
            ),
            evidence_span=None if span is None else (int(span[0]), int(span[1])),
        )


@dataclass(frozen=True)
class EvaluationSpec:
    """How stored grades become relevance and which entity unit is being evaluated."""

    unit: EvaluationUnit = "document"
    relevance_threshold: int = 1
    document_aggregation: Literal["any_chunk"] = "any_chunk"
    boundary: str = "final_retrieval"
    k: int | None = None
    schema_version: int = JUDGMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.relevance_threshold < 1:
            raise ValueError("relevance_threshold must be >= 1; a threshold of 0 would make explicit zero grades relevant")
        if self.k is not None and self.k < 1:
            raise ValueError("k must be None or >= 1")

    def to_dict(self) -> dict:
        return {
            "unit": self.unit,
            "relevance_threshold": self.relevance_threshold,
            "document_aggregation": self.document_aggregation,
            "boundary": self.boundary,
            "k": self.k,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvaluationSpec:
        return cls(
            unit=value.get("unit", "document"),
            relevance_threshold=int(value.get("relevance_threshold", 1)),
            document_aggregation=value.get("document_aggregation", "any_chunk"),
            boundary=str(value.get("boundary", "final_retrieval")),
            k=None if value.get("k") is None else int(value["k"]),
            schema_version=int(value.get("schema_version", JUDGMENT_SCHEMA_VERSION)),
        )

    def digest(self) -> str:
        return _sha256(canonical_json(self.to_dict()))


class DuplicateJudgmentError(ValueError):
    """Two judgments for the same (query, entity) disagree on the grade."""


_Key = Tuple[str, Tuple[str, str, str]]


def _entity_sort_key(entity: EntityRef) -> tuple[str, str, str]:
    return (entity.namespace, entity.unit, entity.entity_id)


def _judgment_sort_key(judgment: Judgment) -> tuple[str, str, str, str]:
    return (judgment.query_id, judgment.entity.namespace, judgment.entity.unit, judgment.entity.entity_id)


class JudgmentSet:
    """Judgments keyed by (query_id, entity.key()). Contradictory duplicates are rejected by default."""

    def __init__(self, judgments: Iterable[Judgment] = (), *, on_conflict: ConflictRule = "error"):
        self._by_key: Dict[_Key, Judgment] = {}
        for judgment in judgments:
            self._add(judgment, on_conflict)

    def _add(self, judgment: Judgment, on_conflict: ConflictRule) -> None:
        key: _Key = (judgment.query_id, judgment.entity.key())
        existing = self._by_key.get(key)
        if existing is None:
            self._by_key[key] = judgment
            return
        if existing.grade == judgment.grade:
            return
        if on_conflict == "error":
            raise DuplicateJudgmentError(
                f"contradictory judgment for query {judgment.query_id!r} entity "
                f"{judgment.entity.namespace}/{judgment.entity.unit}/{judgment.entity.entity_id}: "
                f"grade {judgment.grade} conflicts with grade {existing.grade}"
            )
        if on_conflict == "max":
            if judgment.grade > existing.grade:
                self._by_key[key] = judgment
        elif on_conflict == "last":
            self._by_key[key] = judgment
        elif on_conflict != "first":
            raise ValueError(f"unknown conflict rule {on_conflict!r}")

    @classmethod
    def from_qrels(
        cls,
        qrels: Mapping[str, Mapping[str, int] | Sequence[str]],
        *,
        namespace: str = "default",
        unit: EvaluationUnit = "document",
        source: JudgmentSource = JudgmentSource("gold"),
    ) -> JudgmentSet:
        judgments: List[Judgment] = []
        for query_id, rels in qrels.items():
            pairs = rels.items() if isinstance(rels, Mapping) else ((doc_id, 1) for doc_id in rels or ())
            for doc_id, grade in pairs:
                entity = EntityRef(namespace=namespace, entity_id=str(doc_id), unit=unit)
                judgments.append(Judgment(query_id=str(query_id), entity=entity, grade=int(grade), source=source))
        return cls(judgments)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]], *, on_conflict: ConflictRule = "error") -> JudgmentSet:
        return cls((Judgment.from_record(record) for record in records), on_conflict=on_conflict)

    def to_records(self) -> list[dict]:
        return [judgment.to_record() for judgment in sorted(self._by_key.values(), key=_judgment_sort_key)]

    def to_qrels(self, *, namespace: str | None = None, unit: EvaluationUnit = "document") -> dict[str, dict[str, int]]:
        at_unit = [judgment for judgment in self._by_key.values() if judgment.entity.unit == unit]
        if namespace is None:
            present = sorted({judgment.entity.namespace for judgment in at_unit})
            if len(present) > 1:
                raise ValueError(f"judgments span namespaces {present}; pass namespace= so local ids cannot collide")
            namespace = present[0] if present else "default"
        qrels: dict[str, dict[str, int]] = {}
        for judgment in sorted(at_unit, key=_judgment_sort_key):
            if judgment.entity.namespace == namespace:
                qrels.setdefault(judgment.query_id, {})[judgment.entity.entity_id] = judgment.grade
        return qrels

    def get(self, query_id: str, entity: EntityRef) -> Judgment | None:
        return self._by_key.get((query_id, entity.key()))

    def relevance(self, query_id: str, entity: EntityRef, spec: EvaluationSpec) -> Relevance:
        judgment = self.get(query_id, entity)
        if judgment is None:
            return "unjudged"
        return _grade_relevance(judgment.grade, spec)

    def for_query(self, query_id: str) -> tuple[Judgment, ...]:
        return tuple(sorted((j for j in self._by_key.values() if j.query_id == query_id), key=_judgment_sort_key))

    def judged_entities(self, query_id: str, unit: EvaluationUnit | None = None) -> tuple[EntityRef, ...]:
        return tuple(j.entity for j in self.for_query(query_id) if unit is None or j.entity.unit == unit)

    def relevant_entities(self, query_id: str, spec: EvaluationSpec) -> tuple[EntityRef, ...]:
        return tuple(
            j.entity
            for j in self.for_query(query_id)
            if j.entity.unit == spec.unit and _grade_relevance(j.grade, spec) == "relevant"
        )

    def query_ids(self) -> tuple[str, ...]:
        return tuple(sorted({j.query_id for j in self._by_key.values()}))

    def namespaces(self) -> tuple[str, ...]:
        return tuple(sorted({j.entity.namespace for j in self._by_key.values()}))

    def digest(self) -> str:
        return _sha256(canonical_json({"schema_version": JUDGMENT_SCHEMA_VERSION, "judgments": self.to_records()}))

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self) -> Iterator[Judgment]:
        return iter(sorted(self._by_key.values(), key=_judgment_sort_key))

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[1], EntityRef):
            return False
        return (str(item[0]), item[1].key()) in self._by_key


@dataclass(frozen=True)
class ChunkMap:
    """chunk -> document mapping; each pair is (chunk EntityRef, document EntityRef) in one namespace."""

    pairs: tuple[tuple[EntityRef, EntityRef], ...] = ()
    _by_chunk: Dict[tuple[str, str, str], EntityRef] = field(init=False, repr=False, compare=False)
    _by_document: Dict[tuple[str, str, str], tuple[EntityRef, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_chunk: Dict[tuple[str, str, str], EntityRef] = {}
        by_document: Dict[tuple[str, str, str], list[EntityRef]] = {}
        for chunk, document in self.pairs:
            if chunk.unit != "chunk" or document.unit != "document":
                raise ValueError(f"ChunkMap pairs are (chunk, document); got ({chunk.unit}, {document.unit})")
            if chunk.namespace != document.namespace:
                raise ValueError(f"chunk namespace {chunk.namespace!r} differs from document namespace {document.namespace!r}")
            by_chunk[chunk.key()] = document
            by_document.setdefault(document.key(), []).append(chunk)
        object.__setattr__(self, "_by_chunk", by_chunk)
        object.__setattr__(self, "_by_document", {k: tuple(sorted(v, key=_entity_sort_key)) for k, v in by_document.items()})

    @classmethod
    def from_pairs(
        cls,
        pairs: Iterable[tuple[str, str]] | Iterable[tuple[str, str, str]],
        *,
        namespace: str = "default",
    ) -> ChunkMap:
        built: list[tuple[EntityRef, EntityRef]] = []
        for pair in pairs:
            chunk_id, doc_id = str(pair[0]), str(pair[1])
            pair_namespace = str(pair[2]) if len(pair) > 2 else namespace
            built.append(
                (
                    EntityRef(namespace=pair_namespace, entity_id=chunk_id, unit="chunk"),
                    EntityRef(namespace=pair_namespace, entity_id=doc_id, unit="document"),
                )
            )
        return cls(tuple(built))

    def document_for(self, chunk: EntityRef) -> EntityRef | None:
        return self._by_chunk.get(chunk.key())

    def chunks_for(self, document: EntityRef) -> tuple[EntityRef, ...]:
        return self._by_document.get(document.key(), ())

    def __len__(self) -> int:
        return len(self._by_chunk)


def _grade_relevance(grade: int, spec: EvaluationSpec) -> Relevance:
    return "relevant" if grade >= spec.relevance_threshold else "nonrelevant"


def resolve_relevance(
    judgments: JudgmentSet,
    query_id: str,
    entity: EntityRef,
    spec: EvaluationSpec,
    chunk_map: ChunkMap | None = None,
) -> tuple[Relevance, int | None, str]:
    """Return ``(relevance, grade_or_None, basis)`` for ``entity`` at ``spec.unit``.

    ``basis`` is one of ``direct``, ``document_via_chunk``, ``unmapped``, ``not_inherited``, ``absent``.
    A document judgment is never inherited by its chunks at chunk unit.
    """
    if spec.unit == "document":
        basis = "direct"
        target = entity
        if entity.unit == "chunk":
            target = chunk_map.document_for(entity) if chunk_map is not None else None
            if target is None:
                return ("unjudged", None, "unmapped")
            basis = "document_via_chunk"
        judgment = judgments.get(query_id, target)
        if judgment is None:
            return ("unjudged", None, "absent")
        return (_grade_relevance(judgment.grade, spec), judgment.grade, basis)

    if entity.unit == "document":
        return ("unjudged", None, "not_inherited")
    judgment = judgments.get(query_id, entity)
    if judgment is not None:
        return (_grade_relevance(judgment.grade, spec), judgment.grade, "direct")
    document = chunk_map.document_for(entity) if chunk_map is not None else None
    if document is not None and judgments.get(query_id, document) is not None:
        return ("unjudged", None, "not_inherited")
    return ("unjudged", None, "absent")


def document_included(
    included: Iterable[EntityRef],
    document: EntityRef,
    chunk_map: ChunkMap | None,
    spec: EvaluationSpec,
) -> bool:
    """``any_chunk`` rule: the document counts as included if it or any chunk mapping to it is."""
    keys = {entity.key() for entity in included}
    if document.key() in keys:
        return True
    if chunk_map is None:
        return False
    return any(chunk.key() in keys for chunk in chunk_map.chunks_for(document))


def confusion_cell(relevance: Relevance, included: bool | None) -> ConfusionCell:
    if included is None or relevance == "unjudged":
        return "unknown"
    if relevance == "relevant":
        return "TP" if included else "FN"
    return "FP" if included else "TN"


def confusion_counts(
    judgments: JudgmentSet,
    query_id: str,
    included: Iterable[EntityRef],
    spec: EvaluationSpec,
    chunk_map: ChunkMap | None = None,
) -> dict[str, int]:
    """Confusion counts over the judged universe plus the included entities.

    TN counts only explicitly judged nonrelevant entities that were not included; unseen
    corpus never contributes. ``unknown`` is the included entities with no applicable judgment.
    """
    included_list = list(included)
    judged = judgments.judged_entities(query_id, spec.unit)
    universe: Dict[tuple[str, str, str], EntityRef] = {entity.key(): entity for entity in judged}
    for entity in included_list:
        target = entity
        if spec.unit == "document" and entity.unit == "chunk" and chunk_map is not None:
            target = chunk_map.document_for(entity) or entity
        universe.setdefault(target.key(), target)

    counts = {"TP": 0, "FP": 0, "FN": 0, "TN": 0, "unknown": 0}
    for entity in universe.values():
        relevance, _grade, _basis = resolve_relevance(judgments, query_id, entity, spec, chunk_map)
        if spec.unit == "document" and entity.unit == "document":
            is_included = document_included(included_list, entity, chunk_map, spec)
        else:
            is_included = entity.key() in {item.key() for item in included_list}
        counts[confusion_cell(relevance, is_included)] += 1
    counts["judged"] = len(judged)
    counts["included"] = len({entity.key() for entity in included_list})
    return counts


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, normalised scalars (see ``_normalize``)."""
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalize(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"canonical_json cannot encode {value!r}")
        return 0.0 if value == 0 else value
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(((str(k), v) for k, v in value.items()), key=lambda kv: kv[0])}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def query_input_identity(query: Any) -> str:
    """sha256 of the query's input content: id, text, filters, metadata and temporal anchor.

    ``k`` is deliberately excluded: it is an evaluation parameter (how many results to
    score), not part of the query input, so changing it must not change the identity.
    Accepts a ``Query`` dataclass or a mapping with ``query_id``/``id`` and ``text``/``query``.
    """
    if isinstance(query, Mapping):
        query_id = query.get("query_id", query.get("id", ""))
        text = query.get("text", query.get("query", ""))
        filters = query.get("filters") or {}
        metadata = query.get("metadata") or {}
        anchor = query.get("temporal_anchor")
    else:
        query_id = getattr(query, "query_id", getattr(query, "id", ""))
        text = getattr(query, "text", getattr(query, "query", ""))
        filters = getattr(query, "filters", None) or {}
        metadata = getattr(query, "metadata", None) or {}
        anchor = getattr(query, "temporal_anchor", None)
    if isinstance(anchor, datetime):
        anchor = anchor.isoformat()
    payload = {
        "schema_version": 1,
        "query_id": str(query_id),
        "text": str(text),
        "filters": filters,
        "metadata": metadata,
        "temporal_anchor": None if anchor is None else str(anchor),
    }
    return _sha256(canonical_json(payload))


def queries_input_digest(queries: Iterable[Any]) -> str:
    """Order-independent sha256 over the per-query input identities."""
    return _sha256(canonical_json(sorted(query_input_identity(query) for query in queries)))
