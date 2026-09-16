"""Both qrels row shapes load, and validate_config names the expected shape on a mismatch."""
from __future__ import annotations

from pathlib import Path

import pytest

from retrieval_observatory.config.discovery import validate_config_dict
from retrieval_observatory.datasets.custom import _load_qrels


def test_relevance_rows_and_relevant_doc_id_rows_both_load(tmp_path: Path) -> None:
    rows = tmp_path / "rows.jsonl"
    rows.write_text('{"query_id": "q1", "doc_id": "d2", "relevance": 2}\n{"query_id": "q1", "doc_id": "d3"}\n', encoding="utf-8")
    lists = tmp_path / "lists.jsonl"
    lists.write_text('{"query_id": "q1", "relevant_doc_ids": ["d2", "d3"]}\n{"query_id": "q2", "relevant_doc_ids": {"d4": 3}}\n', encoding="utf-8")
    assert _load_qrels(str(rows)) == {"q1": {"d2": 2, "d3": 1}}
    assert _load_qrels(str(lists)) == {"q1": {"d2": 1, "d3": 1}, "q2": {"d4": 3}}


def test_unknown_row_shape_names_the_accepted_shapes(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"query_id": "q1", "docs": ["d2"]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="relevant_doc_ids") as excinfo:
        _load_qrels(str(bad))
    assert "bad.jsonl:1" in str(excinfo.value)


def _config(tmp_path: Path, qrels_name: str) -> dict:
    return {
        "experiment": {"name": "shape"},
        "dataset": {
            "type": "custom", "name": "custom",
            "queries_path": str(tmp_path / "queries.jsonl"),
            "corpus_path": str(tmp_path / "corpus.jsonl"),
            "qrels_path": str(tmp_path / qrels_name),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }


def test_validate_config_reports_dataset_schema_mismatch(tmp_path: Path) -> None:
    (tmp_path / "queries.jsonl").write_text('{"query_id": "q1", "text": "cats"}\n', encoding="utf-8")
    (tmp_path / "corpus.jsonl").write_text('{"id": "d1", "text": "cats purr"}\n', encoding="utf-8")
    (tmp_path / "wrong.jsonl").write_text('{"qid": "q1", "docid": "d1"}\n', encoding="utf-8")
    (tmp_path / "right.jsonl").write_text('{"query_id": "q1", "doc_id": "d1", "relevance": 1}\n', encoding="utf-8")

    report = validate_config_dict(_config(tmp_path, "wrong.jsonl"))
    assert report["valid"] is False
    item = next(item for item in report["items"] if item.get("field") == "dataset.qrels_path")
    assert item["level"] == "error"
    assert "['docid', 'qid']" in item["message"] and "relevant_doc_ids" in item["message"]

    report = validate_config_dict(_config(tmp_path, "right.jsonl"))
    assert report["valid"] is True
    assert {item["field"] for item in report["items"] if item["level"] == "ok" and str(item.get("field", "")).startswith("dataset.")} == {
        "dataset.queries_path", "dataset.corpus_path", "dataset.qrels_path",
    }
