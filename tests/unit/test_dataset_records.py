"""``retobs evaluate``'s file reading: a one-row JSONL file is one record; a ``.json`` object stays a mapping."""
from __future__ import annotations

from pathlib import Path

from retrieval_observatory.datasets.records import evaluate_inputs, read_json_records


def test_one_row_jsonl_corpus_and_queries_are_one_record_each(tmp_path: Path) -> None:
    queries = tmp_path / "queries.jsonl"
    queries.write_text('{"query_id": "q1", "text": "widget pricing"}\n', encoding="utf-8")
    corpus = tmp_path / "corpus.JSONL"
    corpus.write_text('{"id": "d1", "text": "pricing"}\n', encoding="utf-8")
    qrels = tmp_path / "qrels.jsonl"
    qrels.write_text('{"query_id": "q1", "relevant_doc_ids": ["d1"]}\n', encoding="utf-8")

    query_rows, corpus_map, qrel_map = evaluate_inputs(None, queries, corpus, qrels)

    assert query_rows == [{"query_id": "q1", "text": "widget pricing"}]
    assert corpus_map == {"d1": "pricing"}
    assert qrel_map == {"q1": ["d1"]}


def test_json_files_keep_their_shape(tmp_path: Path) -> None:
    mapping = tmp_path / "corpus.json"
    mapping.write_text('{"d1": "pricing", "d2": "setup"}', encoding="utf-8")
    rows = tmp_path / "queries.json"
    rows.write_text('[{"query_id": "q1", "text": "a"}, {"query_id": "q2", "text": "b"}]', encoding="utf-8")
    one_row = tmp_path / "qrels.json"
    one_row.write_text('{"query_id": "q1", "doc_id": "d1", "relevance": 1}', encoding="utf-8")

    assert read_json_records(mapping) == {"d1": "pricing", "d2": "setup"}
    assert read_json_records(rows) == [{"query_id": "q1", "text": "a"}, {"query_id": "q2", "text": "b"}]
    assert read_json_records(one_row) == [{"query_id": "q1", "doc_id": "d1", "relevance": 1}]
