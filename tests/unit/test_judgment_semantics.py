from __future__ import annotations

from datetime import datetime

import pytest

from retrieval_observatory.datasets.judgments import (
    JUDGMENT_SCHEMA_VERSION,
    ChunkMap,
    DuplicateJudgmentError,
    EntityRef,
    EvaluationSpec,
    Judgment,
    JudgmentSet,
    JudgmentSource,
    canonical_json,
    confusion_counts,
    document_included,
    queries_input_digest,
    query_input_identity,
    resolve_relevance,
)
from retrieval_observatory.types import Query

GOLD = JudgmentSource("gold")


def _doc(entity_id: str, namespace: str = "default") -> EntityRef:
    return EntityRef(namespace=namespace, entity_id=entity_id, unit="document")


def _chunk(entity_id: str, namespace: str = "default") -> EntityRef:
    return EntityRef(namespace=namespace, entity_id=entity_id, unit="chunk")


def _judgment(query_id: str, entity: EntityRef, grade: int, source: JudgmentSource = GOLD) -> Judgment:
    return Judgment(query_id=query_id, entity=entity, grade=grade, source=source)


def test_absent_judgment_is_unjudged_not_negative():
    judgments = JudgmentSet.from_qrels({"q1": {"d1": 1}})
    spec = EvaluationSpec()
    assert judgments.relevance("q1", _doc("d1"), spec) == "relevant"
    assert judgments.relevance("q1", _doc("never-judged"), spec) == "unjudged"
    assert judgments.get("q1", _doc("never-judged")) is None
    assert resolve_relevance(judgments, "q1", _doc("never-judged"), spec) == ("unjudged", None, "absent")
    assert ("q1", _doc("never-judged")) not in judgments
    assert ("q1", _doc("d1")) in judgments


def test_zero_grade_survives_roundtrip_and_is_nonrelevant():
    judgments = JudgmentSet.from_qrels({"q1": {"d": 0, "e": 2}})
    records = judgments.to_records()
    rebuilt = JudgmentSet.from_records(records)
    assert rebuilt.to_qrels() == {"q1": {"d": 0, "e": 2}}
    assert rebuilt.relevance("q1", _doc("d"), EvaluationSpec()) == "nonrelevant"
    assert rebuilt.get("q1", _doc("d")).grade == 0


def test_threshold_derives_relevance_from_stored_grade():
    judgments = JudgmentSet.from_qrels({"q1": {"d1": 1}})
    assert judgments.relevance("q1", _doc("d1"), EvaluationSpec(relevance_threshold=1)) == "relevant"
    assert judgments.relevance("q1", _doc("d1"), EvaluationSpec(relevance_threshold=2)) == "nonrelevant"
    assert judgments.get("q1", _doc("d1")).grade == 1
    assert judgments.relevant_entities("q1", EvaluationSpec(relevance_threshold=2)) == ()
    with pytest.raises(ValueError):
        EvaluationSpec(relevance_threshold=0)
    with pytest.raises(ValueError):
        EvaluationSpec(k=0)


def test_contradictory_duplicates_rejected_without_rule():
    with pytest.raises(DuplicateJudgmentError) as excinfo:
        JudgmentSet([_judgment("q1", _doc("d1"), 1), _judgment("q1", _doc("d1"), 2)])
    message = str(excinfo.value)
    assert "'q1'" in message and "d1" in message and "grade 2" in message and "grade 1" in message


def test_conflict_rules_resolve_deterministically():
    rows = [_judgment("q1", _doc("d1"), 1), _judgment("q1", _doc("d1"), 3), _judgment("q1", _doc("d1"), 2)]
    assert JudgmentSet(rows, on_conflict="max").get("q1", _doc("d1")).grade == 3
    assert JudgmentSet(rows, on_conflict="first").get("q1", _doc("d1")).grade == 1
    assert JudgmentSet(rows, on_conflict="last").get("q1", _doc("d1")).grade == 2
    assert len(JudgmentSet(rows, on_conflict="max")) == 1
    records = [j.to_record() for j in rows]
    assert JudgmentSet.from_records(records, on_conflict="max").get("q1", _doc("d1")).grade == 3


def test_identical_duplicates_collapse():
    judgments = JudgmentSet([_judgment("q1", _doc("d1"), 1), _judgment("q1", _doc("d1"), 1)])
    assert len(judgments) == 1
    assert judgments.to_qrels() == {"q1": {"d1": 1}}


def test_same_local_id_in_two_namespaces_are_distinct_entities():
    judgments = JudgmentSet([_judgment("q1", _doc("d1", "a"), 1), _judgment("q1", _doc("d1", "b"), 0)])
    assert len(judgments) == 2
    assert judgments.namespaces() == ("a", "b")
    assert judgments.judged_entities("q1") == (_doc("d1", "a"), _doc("d1", "b"))
    assert judgments.relevance("q1", _doc("d1", "a"), EvaluationSpec()) == "relevant"
    assert judgments.relevance("q1", _doc("d1", "b"), EvaluationSpec()) == "nonrelevant"
    with pytest.raises(ValueError):
        judgments.to_qrels()
    assert judgments.to_qrels(namespace="a") == {"q1": {"d1": 1}}
    assert judgments.to_qrels(namespace="b") == {"q1": {"d1": 0}}


def test_digest_is_order_independent_and_sensitive_to_grade_source_and_schema():
    a, b = _judgment("q1", _doc("d1"), 1), _judgment("q2", _doc("d2"), 2)
    base = JudgmentSet([a, b]).digest()
    assert JudgmentSet([b, a]).digest() == base
    assert len(base) == 64
    assert JudgmentSet([a, _judgment("q2", _doc("d2"), 1)]).digest() != base
    assert JudgmentSet([a, _judgment("q2", _doc("d3"), 2)]).digest() != base
    assert JudgmentSet([a, _judgment("q2", _doc("d2"), 2, JudgmentSource("llm_judge"))]).digest() != base
    assert JudgmentSet([a, _judgment("q2", _doc("d2"), 2, JudgmentSource("gold", "v2"))]).digest() != base
    assert JudgmentSet([a, _judgment("q2", _doc("d2", "other"), 2)]).digest() != base
    assert JudgmentSet([a, _judgment("q2", _chunk("d2"), 2)]).digest() != base
    # The digest is bound to the schema version: bumping it must change every digest.
    assert canonical_json({"schema_version": JUDGMENT_SCHEMA_VERSION, "judgments": []}) != canonical_json(
        {"schema_version": JUDGMENT_SCHEMA_VERSION + 1, "judgments": []}
    )


def test_query_input_identity_changes_with_text_filters_metadata_but_not_key_order_or_k():
    base = query_input_identity(Query(text="hello", k=10, query_id="q1", filters={"a": 1, "b": 2}, metadata={"x": 1}))
    assert query_input_identity(Query(text="hello", k=50, query_id="q1", filters={"b": 2, "a": 1}, metadata={"x": 1})) == base
    assert query_input_identity({"query_id": "q1", "text": "hello", "filters": {"a": 1, "b": 2}, "metadata": {"x": 1}}) == base
    assert query_input_identity({"id": "q1", "query": "hello", "filters": {"a": 1, "b": 2}, "metadata": {"x": 1}}) == base
    assert query_input_identity(Query(text="hello!", query_id="q1", filters={"a": 1, "b": 2}, metadata={"x": 1})) != base
    assert query_input_identity(Query(text="hello", query_id="q1", filters={"a": 1}, metadata={"x": 1})) != base
    assert query_input_identity(Query(text="hello", query_id="q1", filters={"a": 1, "b": 2}, metadata={"x": 2})) != base
    assert query_input_identity(Query(text="hello", query_id="q2", filters={"a": 1, "b": 2}, metadata={"x": 1})) != base
    anchored = Query(text="hello", query_id="q1", filters={"a": 1, "b": 2}, metadata={"x": 1}, temporal_anchor=datetime(2024, 1, 3))
    assert query_input_identity(anchored) != base


def test_queries_input_digest_is_order_independent():
    q1 = {"query_id": "q1", "text": "one"}
    q2 = {"query_id": "q2", "text": "two"}
    assert queries_input_digest([q1, q2]) == queries_input_digest([q2, q1])
    assert queries_input_digest([q1, q2]) != queries_input_digest([q1])
    assert queries_input_digest([q1, {"query_id": "q2", "text": "two", "metadata": {"m": 1}}]) != queries_input_digest([q1, q2])


def test_document_included_by_any_mapped_chunk():
    chunk_map = ChunkMap.from_pairs([("c1", "d1"), ("c2", "d1"), ("c3", "d2")])
    spec = EvaluationSpec(unit="document")
    assert document_included([_chunk("c2")], _doc("d1"), chunk_map, spec) is True
    assert document_included([_doc("d1")], _doc("d1"), chunk_map, spec) is True
    assert document_included([_chunk("c3")], _doc("d1"), chunk_map, spec) is False
    assert document_included([_chunk("c2")], _doc("d1"), None, spec) is False
    # Namespace-aware: a chunk with the same local id in another namespace does not count.
    assert document_included([_chunk("c2", "other")], _doc("d1"), chunk_map, spec) is False
    assert chunk_map.chunks_for(_doc("d1")) == (_chunk("c1"), _chunk("c2"))
    assert len(chunk_map) == 3


def test_document_grade_is_not_inherited_by_chunks_at_chunk_unit():
    judgments = JudgmentSet.from_qrels({"q1": {"d1": 2}})
    chunk_map = ChunkMap.from_pairs([("c1", "d1")])
    chunk_spec = EvaluationSpec(unit="chunk")
    assert resolve_relevance(judgments, "q1", _chunk("c1"), chunk_spec, chunk_map) == ("unjudged", None, "not_inherited")
    assert resolve_relevance(judgments, "q1", _doc("d1"), chunk_spec, chunk_map) == ("unjudged", None, "not_inherited")
    assert resolve_relevance(judgments, "q1", _chunk("c9"), chunk_spec, chunk_map) == ("unjudged", None, "absent")
    assert judgments.relevant_entities("q1", chunk_spec) == ()
    # A chunk judgment is found directly at chunk unit; the document one at document unit.
    with_chunk = JudgmentSet(list(judgments) + [_judgment("q1", _chunk("c1"), 1)])
    assert resolve_relevance(with_chunk, "q1", _chunk("c1"), chunk_spec, chunk_map) == ("relevant", 1, "direct")
    doc_spec = EvaluationSpec(unit="document")
    assert resolve_relevance(with_chunk, "q1", _chunk("c1"), doc_spec, chunk_map) == ("relevant", 2, "document_via_chunk")
    assert resolve_relevance(with_chunk, "q1", _doc("d1"), doc_spec, chunk_map) == ("relevant", 2, "direct")


def test_unmapped_chunk_is_unjudged_at_document_unit():
    judgments = JudgmentSet.from_qrels({"q1": {"d1": 1}})
    spec = EvaluationSpec(unit="document")
    assert resolve_relevance(judgments, "q1", _chunk("c1"), spec, None) == ("unjudged", None, "unmapped")
    assert resolve_relevance(judgments, "q1", _chunk("c1"), spec, ChunkMap.from_pairs([("c2", "d1")])) == ("unjudged", None, "unmapped")


def test_confusion_counts_use_only_the_judged_universe():
    judgments = JudgmentSet.from_qrels({"q1": {"rel_in": 1, "rel_out": 2, "non_in": 0, "non_out": 0}})
    spec = EvaluationSpec(unit="document")
    included = [_doc("rel_in"), _doc("non_in"), _doc("unjudged_in")]
    counts = confusion_counts(judgments, "q1", included, spec)
    assert counts == {"TP": 1, "FP": 1, "FN": 1, "TN": 1, "unknown": 1, "judged": 4, "included": 3}
    # The corpus may hold thousands of unjudged, unretrieved docs; they contribute nothing.
    assert sum(counts[cell] for cell in ("TP", "FP", "FN", "TN", "unknown")) == 5
    # Chunks map to documents under any_chunk; an unmapped chunk is unknown.
    chunk_map = ChunkMap.from_pairs([("c_rel", "rel_in"), ("c_non", "non_in")])
    counts = confusion_counts(judgments, "q1", [_chunk("c_rel"), _chunk("c_non"), _chunk("c_orphan")], spec, chunk_map)
    assert counts == {"TP": 1, "FP": 1, "FN": 1, "TN": 1, "unknown": 1, "judged": 4, "included": 3}
    assert confusion_counts(judgments, "q1", [], spec) == {"TP": 0, "FP": 0, "FN": 2, "TN": 2, "unknown": 0, "judged": 4, "included": 0}


def test_canonical_json_normalises_scalars():
    assert canonical_json({"b": 1, "a": True}) == '{"a":true,"b":1}'
    assert canonical_json([True, 1, 1.0]) == "[true,1,1.0]"
    assert canonical_json(-0.0) == "0.0"
    assert canonical_json({3, 1, 2}) == "[1,2,3]"
    assert canonical_json([3, 1, 2]) == "[3,1,2]"
    assert canonical_json((3, 1)) == "[3,1]"
    assert canonical_json({"when": datetime(2024, 1, 3)}) == '{"when":"2024-01-03T00:00:00"}'
    assert canonical_json({1: "x"}) == '{"1":"x"}'
    with pytest.raises(ValueError):
        canonical_json(float("nan"))
    with pytest.raises(ValueError):
        canonical_json({"v": float("inf")})
