"""``retobs evaluate --qrels`` accepts one-pair-per-row judgments as well as relevant_doc_ids lists."""
from __future__ import annotations

import json
from pathlib import Path

from retrieval_observatory.cli import _evaluate_inputs


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_row_format_qrels_are_graded_per_query(tmp_path: Path) -> None:
    queries = _write(tmp_path / "queries.jsonl", [{"query_id": "q1", "text": "a"}, {"query_id": "q2", "text": "b"}])
    corpus = _write(tmp_path / "corpus.jsonl", [{"id": "d1", "text": "x"}, {"id": "d2", "text": "y"}])
    rows = _write(tmp_path / "qrels.jsonl", [
        {"query_id": "q1", "doc_id": "d1", "relevance": 2},
        {"query_id": "q1", "doc_id": "d2", "relevance": 1},
        {"query_id": "q2", "doc_id": "d2", "relevance": 1},
    ])
    _, _, qrels = _evaluate_inputs(None, queries, corpus, rows)
    assert qrels == {"q1": {"d1": 2, "d2": 1}, "q2": {"d2": 1}}

    lists = _write(tmp_path / "qrels_lists.jsonl", [{"query_id": "q1", "relevant_doc_ids": ["d1"]}])
    _, _, qrels = _evaluate_inputs(None, queries, corpus, lists)
    assert qrels == {"q1": ["d1"]}
