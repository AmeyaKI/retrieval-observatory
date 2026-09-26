"""``evaluate(chunk_map=)`` scores chunk results against document-level qrels.

Expected values are hand-computed from the definitions (linear-gain nDCG, dedupe-then-cut), never
read back from the metrics engine.
"""

from __future__ import annotations

import json
import math
import sqlite3

import pytest

import retrieval_observatory as ro
from retrieval_observatory.datasets.judgments import ChunkMap, EntityRef, JudgmentSet
from retrieval_observatory.sdk.observe import observe

QUERIES = [{"query_id": "q1", "text": "alpha"}, {"query_id": "q2", "text": "beta"}]
QRELS = {"q1": {"doc-a": 2, "doc-b": 1}, "q2": {"doc-c": 1}}
METRICS = {"recall_at_k": [4], "ndcg_at_k": [4], "precision_at_k": [4]}
CHUNK_RESULTS = {
    "alpha": ["doc-a#0", "doc-a#1", "doc-x#0", "doc-b#0"],  # two chunks of the grade-2 document
    "beta": ["doc-d#0", "doc-c#0"],
}
CHUNK_MAP = [(chunk, chunk.split("#")[0]) for chunks in CHUNK_RESULTS.values() for chunk in chunks]


def chunk_pipeline(query: str) -> list[str]:
    return CHUNK_RESULTS[query]


def document_pipeline(query: str) -> list[str]:
    return {"alpha": ["doc-x", "doc-a", "doc-y", "doc-b"], "beta": ["doc-c"]}[query]


def _evaluate(tmp_path, pipeline, name: str, chunk_map=None):
    db = str(tmp_path / f"{name}.db")
    report = ro.evaluate(pipeline, queries=QUERIES, qrels=QRELS, k=5, db_path=db, metrics=METRICS, chunk_map=chunk_map)
    return report, db


def _quality(db: str, run_id: str) -> dict[tuple[str, str, int], float]:
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT query_id, metric_name, k, value FROM metric_scores WHERE run_id = ? AND stage_index = 0 AND metric_name != 'latency_ms'",
            (run_id,),
        ).fetchall()
    return {(query_id, name, k): value for query_id, name, k, value in rows}


def _manifest(db: str, run_id: str) -> dict:
    with sqlite3.connect(db) as con:
        return json.loads(con.execute("SELECT manifest_json FROM run_manifests WHERE run_id = ?", (run_id,)).fetchone()[0])


def _dcg(gains: list[int]) -> float:
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))


def test_chunk_results_score_against_document_qrels_with_duplicates_collapsed(tmp_path) -> None:
    report, db = _evaluate(tmp_path, chunk_pipeline, "mapped", CHUNK_MAP)

    # q1 documents in rank order: doc-a (chunk #0; chunk #1 collapses into it), doc-x, doc-b.
    q1_ndcg = _dcg([2, 0, 1]) / _dcg([2, 1])
    # q2 documents: doc-d, doc-c.
    q2_ndcg = _dcg([0, 1]) / _dcg([1])
    assert _quality(db, report.run_id) == pytest.approx({
        ("q1", "recall", 4): 1.0,
        ("q1", "precision", 4): 2 / 4,
        ("q1", "ndcg", 4): q1_ndcg,
        ("q1", "mrr", 0): 1.0,
        ("q1", "map", 0): (1 / 1 + 2 / 3) / 2,
        ("q2", "recall", 4): 1.0,
        ("q2", "precision", 4): 1 / 4,
        ("q2", "ndcg", 4): q2_ndcg,
        ("q2", "mrr", 0): 1 / 2,
        ("q2", "map", 0): 1 / 2,
    })
    assert q1_ndcg == pytest.approx(0.950234, abs=1e-6)  # < 1: the duplicate chunk earns no second gain


def test_without_chunk_map_chunk_ids_stay_unmatched(tmp_path) -> None:
    report, db = _evaluate(tmp_path, chunk_pipeline, "unmapped")

    assert set(_quality(db, report.run_id).values()) == {0.0}


def test_document_pipeline_without_chunk_map_is_scored_on_raw_ids(tmp_path) -> None:
    report, db = _evaluate(tmp_path, document_pipeline, "documents")

    assert _quality(db, report.run_id) == pytest.approx({
        ("q1", "recall", 4): 1.0,
        ("q1", "precision", 4): 2 / 4,
        ("q1", "ndcg", 4): _dcg([0, 2, 0, 1]) / _dcg([2, 1]),
        ("q1", "mrr", 0): 1 / 2,
        ("q1", "map", 0): (1 / 2 + 2 / 4) / 2,
        ("q2", "recall", 4): 1.0,
        ("q2", "precision", 4): 1 / 4,
        ("q2", "ndcg", 4): 1.0,
        ("q2", "mrr", 0): 1.0,
        ("q2", "map", 0): 1.0,
    })
    with sqlite3.connect(db) as con:
        (saved_qrels,) = con.execute("SELECT qrels_json FROM run_qrels WHERE run_id = ?", (report.run_id,)).fetchone()
    assert json.loads(saved_qrels) == QRELS  # un-namespaced: this path is unchanged


def test_manifest_judgments_and_projection_follow_the_document_qrels(tmp_path) -> None:
    mapped, mapped_db = _evaluate(tmp_path, chunk_pipeline, "mapped", CHUNK_MAP)
    plain, plain_db = _evaluate(tmp_path, document_pipeline, "documents")
    expected = JudgmentSet.from_qrels(QRELS)

    manifest = _manifest(mapped_db, mapped.run_id)
    assert manifest["judgment_records"] == expected.to_records()
    assert manifest["judgment_digest"] == expected.digest()
    assert manifest["investigation_projection"] == {"chunk_pipeline": {"status": "complete", "row_count": 5}}
    # The dataset identity is the caller's qrels, so a chunk-mapped run compares with a document run.
    plain_manifest = _manifest(plain_db, plain.run_id)
    for key in ("judgment_digest", "qrel_hash"):
        assert manifest["dataset"][key] == plain_manifest["dataset"][key]
    assert manifest["judgment_digest"] == plain_manifest["judgment_digest"]

    document = ro.inspect_document(mapped.run_id, "default:doc-a", db_path=mapped_db)
    assert document["capabilities"]["projection"] == "ready"
    assert [(row["query_id"], row["namespace"], row["entity_id"], row["judgment"], row["outcome"]) for row in document["rows"]] == [
        ("q1", "default", "doc-a", "relevant", "relevant_delivered")
    ]


def test_corpus_membership_diagnostic_compares_documents_in_one_namespace(tmp_path) -> None:
    corpus = {doc_id: f"text of {doc_id}" for doc_id in ("doc-a", "doc-c", "doc-d", "doc-x")}  # doc-b is absent
    db = str(tmp_path / "corpus.db")
    report = ro.evaluate(chunk_pipeline, queries=QUERIES, qrels=QRELS, corpus=corpus, k=5, db_path=db, metrics=METRICS, chunk_map=CHUNK_MAP)

    with sqlite3.connect(db) as con:
        findings = [(query_id, json.loads(payload)) for query_id, payload in con.execute(
            "SELECT query_id, finding_json FROM diagnostic_findings WHERE run_id = ?", (report.run_id,)
        )]
    absent = {query_id: finding for query_id, finding in findings if finding["label"] == "qrel_absent_from_corpus"}
    assert absent["q1"]["availability"] == "supported"
    assert absent["q2"]["availability"] == "not_observed"  # doc-c is in the corpus


@observe("SOURCE", op_id="search")
def kb_pipeline(query: str) -> list[dict]:
    """Chunks that carry their namespace, as an application's own search results do."""
    return [{"id": chunk, "metadata": {"namespace": "kb"}} for chunk in CHUNK_RESULTS[query]]


def test_namespaced_chunk_map_places_judged_documents_in_its_namespace(tmp_path) -> None:
    kb_map = [(chunk, document, "kb") for chunk, document in CHUNK_MAP]
    report, db = _evaluate(tmp_path, kb_pipeline, "kb", kb_map)

    quality = _quality(db, report.run_id)
    # Same ranked documents as the default-namespace case: q1 doc-a, doc-x, doc-b; q2 doc-d, doc-c.
    assert {key: quality[key] for key in (("q1", "recall", 4), ("q2", "recall", 4), ("q1", "mrr", 0), ("q2", "mrr", 0))} == pytest.approx(
        {("q1", "recall", 4): 1.0, ("q2", "recall", 4): 1.0, ("q1", "mrr", 0): 1.0, ("q2", "mrr", 0): 1 / 2}
    )
    assert quality[("q1", "ndcg", 4)] == pytest.approx(_dcg([2, 0, 1]) / _dcg([2, 1]))
    manifest = _manifest(db, report.run_id)
    assert {(r["query_id"], r["namespace"], r["entity_id"]) for r in manifest["judgment_records"]} == {
        ("q1", "kb", "doc-a"), ("q1", "kb", "doc-b"), ("q2", "kb", "doc-c")
    }
    assert manifest["dataset"]["judgment_digest"] == JudgmentSet.from_qrels(QRELS).digest()  # the caller's qrels
    document = ro.inspect_document(report.run_id, "kb:doc-a", db_path=db)
    assert [(row["query_id"], row["outcome"]) for row in document["rows"]] == [("q1", "relevant_delivered")]


def test_documents_the_chunk_map_does_not_mention_stay_in_default(tmp_path) -> None:
    partial_map = [(chunk, document, "kb") for chunk, document in CHUNK_MAP if document != "doc-c"]
    report, db = _evaluate(tmp_path, kb_pipeline, "partial", partial_map)

    records = _manifest(db, report.run_id)["judgment_records"]
    assert {(r["namespace"], r["entity_id"]) for r in records} == {("kb", "doc-a"), ("kb", "doc-b"), ("default", "doc-c")}


def test_judged_document_in_two_namespaces_is_rejected(tmp_path) -> None:
    ambiguous = [*CHUNK_MAP, ("doc-a#9", "doc-a", "archive")]

    with pytest.raises(ValueError, match=r"qrels document 'doc-a' is in chunk_map namespaces \['archive', 'default'\]"):
        _evaluate(tmp_path, chunk_pipeline, "ambiguous", ambiguous)


KB_MAP = [(chunk, document, "kb") for chunk, document in CHUNK_MAP]


def test_bare_chunk_ids_take_the_one_namespace_the_chunk_map_gives_them(tmp_path) -> None:
    """A plain callable returns bare ids (no namespace); every id is mapped only under ``kb``."""
    report, db = _evaluate(tmp_path, chunk_pipeline, "bare-kb", KB_MAP)

    quality = _quality(db, report.run_id)
    assert {key: quality[key] for key in (("q1", "recall", 4), ("q1", "ndcg", 4), ("q2", "recall", 4), ("q2", "ndcg", 4))} == pytest.approx({
        ("q1", "recall", 4): 1.0,
        ("q1", "ndcg", 4): _dcg([2, 0, 1]) / _dcg([2, 1]),  # doc-a, doc-x, doc-b
        ("q2", "recall", 4): 1.0,
        ("q2", "ndcg", 4): _dcg([0, 1]) / _dcg([1]),  # doc-d, doc-c
    })
    document = ro.inspect_document(report.run_id, "kb:doc-a", db_path=db)
    assert [(row["query_id"], row["judgment"], row["outcome"]) for row in document["rows"]] == [("q1", "relevant", "relevant_delivered")]


def test_bare_chunk_id_under_two_namespaces_stays_unmapped(tmp_path) -> None:
    ambiguous = [*KB_MAP, ("doc-b#0", "doc-z", "archive")]  # doc-b's only chunk is also an archive chunk
    report, db = _evaluate(tmp_path, chunk_pipeline, "bare-ambiguous", ambiguous)

    quality = _quality(db, report.run_id)
    # q1 documents: kb:doc-a, kb:doc-x, then the unresolved chunk (default:doc-b#0), which earns nothing.
    assert {key: quality[key] for key in (("q1", "recall", 4), ("q1", "ndcg", 4))} == pytest.approx({
        ("q1", "recall", 4): 1 / 2,
        ("q1", "ndcg", 4): _dcg([2, 0, 0]) / _dcg([2, 1]),
    })
    unresolved = ro.inspect_document(report.run_id, "default:doc-b#0", db_path=db)
    assert [(row["query_id"], row["judgment"], row["final_membership"]) for row in unresolved["rows"]] == [("q1", "unmapped", "included")]
    judged = ro.inspect_document(report.run_id, "kb:doc-b", db_path=db)
    assert [(row["query_id"], row["judgment"], row["outcome"]) for row in judged["rows"]] == [("q1", "relevant", "not_observed")]


def test_chunk_ref_prefers_explicit_then_default_then_the_only_namespace() -> None:
    chunks = ChunkMap.from_pairs([("c1", "d1"), ("c1", "d1", "kb"), ("c2", "d2", "kb"), ("c3", "d3", "kb"), ("c3", "d9", "archive")])

    assert chunks.chunk_ref("c1") == EntityRef("default", "c1", "chunk")  # a default row wins, as before
    assert chunks.chunk_ref("c2") == EntityRef("kb", "c2", "chunk")  # the only namespace
    assert chunks.chunk_ref("c3") == EntityRef("default", "c3", "chunk")  # ambiguous: not guessed
    assert chunks.document_for(chunks.chunk_ref("c3")) is None
    assert chunks.chunk_ref("c2", "other") == EntityRef("other", "c2", "chunk")  # explicit namespace is kept
    assert chunks.chunk_ref("unknown") == EntityRef("default", "unknown", "chunk")


@observe("SOURCE", op_id="search")
def document_named_pipeline(query: str) -> list[dict]:
    """Chunks that name their document but no namespace: identity is not inferred from the chunk map."""
    return [{"id": chunk, "document_id": chunk.split("#")[0]} for chunk in CHUNK_RESULTS[query]]


def test_candidates_naming_their_document_keep_the_default_namespace(tmp_path) -> None:
    report, db = _evaluate(tmp_path, document_named_pipeline, "named-kb", KB_MAP)

    quality = _quality(db, report.run_id)
    assert quality[("q1", "recall", 4)] == 0.0  # default:doc-a is not the judged kb:doc-a
    document = ro.inspect_document(report.run_id, "kb:doc-a", db_path=db)
    assert [(row["query_id"], row["outcome"]) for row in document["rows"]] == [("q1", "not_observed")]  # the projection agrees
