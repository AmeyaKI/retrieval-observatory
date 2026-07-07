from __future__ import annotations

from retrieval_observatory.datasets.validation import detect_near_duplicate_queries


def test_detects_near_duplicate_queries():
    queries = [
        {"query_id": "q1", "text": "What is the capital of France"},
        {"query_id": "q2", "text": "What is the capital city of France"},
        {"query_id": "q3", "text": "How does photosynthesis work in plants"},
    ]
    flagged = detect_near_duplicate_queries(queries, threshold=0.7)
    pairs = {frozenset((d["query_id_a"], d["query_id_b"])) for d in flagged}
    assert frozenset(("q1", "q2")) in pairs
    assert not any("q3" in pair for pair in pairs)


def test_no_false_positive_on_distinct_queries():
    queries = [
        {"query_id": "q1", "text": "What is the capital of France"},
        {"query_id": "q2", "text": "How does photosynthesis work in plants"},
    ]
    assert detect_near_duplicate_queries(queries, threshold=0.8) == []


def test_ignores_queries_with_empty_text():
    queries = [
        {"query_id": "q1", "text": ""},
        {"query_id": "q2", "text": "What is the capital of France"},
    ]
    assert detect_near_duplicate_queries(queries, threshold=0.5) == []
