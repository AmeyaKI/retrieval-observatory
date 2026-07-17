"""Unit tests for Test Sets ground truth building."""
from __future__ import annotations

from retrieval_observatory.forge.labels.ground_truth import build_extractive_qrels
from retrieval_observatory.forge.types import SyntheticQuery


def _make_query(query_id: str, positive_ids: list) -> SyntheticQuery:
    return SyntheticQuery(
        query_id=query_id,
        text="test query",
        scenario_id="s1",
        query_type="paraphrase",
        positive_doc_ids=positive_ids,
    )


class TestBuildExtractiveQrels:
    def test_single_query_single_doc(self):
        queries = [_make_query("q1", ["doc1"])]
        qrels = build_extractive_qrels(queries)
        assert qrels == {"q1": {"doc1": 2}}

    def test_single_query_multiple_docs(self):
        queries = [_make_query("q1", ["doc1", "doc2"])]
        qrels = build_extractive_qrels(queries)
        assert qrels["q1"]["doc1"] == 2
        assert qrels["q1"]["doc2"] == 2

    def test_multiple_queries(self):
        queries = [
            _make_query("q1", ["doc1"]),
            _make_query("q2", ["doc2", "doc3"]),
        ]
        qrels = build_extractive_qrels(queries)
        assert "q1" in qrels
        assert "q2" in qrels
        assert qrels["q2"]["doc3"] == 2

    def test_empty_query_list(self):
        assert build_extractive_qrels([]) == {}

    def test_all_grades_are_2(self):
        queries = [_make_query(f"q{i}", [f"doc{i}"]) for i in range(5)]
        qrels = build_extractive_qrels(queries)
        for grades in qrels.values():
            assert all(g == 2 for g in grades.values())

    def test_empty_positive_ids(self):
        queries = [_make_query("q1", [])]
        qrels = build_extractive_qrels(queries)
        assert qrels == {"q1": {}}
