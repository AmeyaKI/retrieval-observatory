from datetime import datetime, timedelta

import pytest

from retrieval_observatory.metrics.ranking import average_precision, map_score, mrr, ndcg_at_k
from retrieval_observatory.metrics.recall import recall_at_k, temporal_recall_at_k
from retrieval_observatory.metrics.significance import bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.types import Document


def test_recall_at_k_perfect():
    assert recall_at_k(["d1", "d2", "d3"], {"d1", "d2"}, k=3) == 1.0


def test_recall_at_k_partial():
    assert recall_at_k(["d1", "d4", "d5"], {"d1", "d2"}, k=3) == 0.5


def test_recall_at_k_zero():
    assert recall_at_k(["d3", "d4"], {"d1", "d2"}, k=2) == 0.0


def test_recall_at_k_empty_relevant():
    assert recall_at_k(["d1"], set(), k=1) == 0.0


def test_mrr_basic():
    result = mrr([["d2", "d1", "d3"]], [{"d1"}])
    assert abs(result - 0.5) < 1e-9


def test_mrr_first_hit():
    result = mrr([["d1", "d2"]], [{"d1"}])
    assert result == 1.0


def test_ndcg_at_k_perfect():
    score = ndcg_at_k(["d1", "d2"], {"d1", "d2"}, k=2)
    assert abs(score - 1.0) < 1e-6


def test_ndcg_at_k_zero():
    score = ndcg_at_k(["d3", "d4"], {"d1", "d2"}, k=2)
    assert score == 0.0


def test_average_precision():
    ap = average_precision(["d1", "d3", "d2"], {"d1", "d2"})
    # Hits at rank 1 (precision=1/1) and rank 3 (precision=2/3)
    expected = (1.0 + 2.0 / 3.0) / 2
    assert abs(ap - expected) < 1e-6


def test_map_score():
    score = map_score([["d1", "d2"], ["d3", "d1"]], [{"d1"}, {"d3"}])
    assert 0.0 <= score <= 1.0


def test_temporal_recall_exponential():
    anchor = datetime(2024, 1, 15)
    docs = [
        Document(id="d1", text="", score=1.0, rank=1, timestamp=datetime(2024, 1, 14)),
        Document(id="d2", text="", score=0.9, rank=2, timestamp=datetime(2023, 6, 1)),
    ]
    # d1 is recent (high weight), d2 is old (low weight)
    score = temporal_recall_at_k(docs, {"d1"}, k=2, query_anchor=anchor)
    assert 0.0 < score <= 1.0


def test_temporal_recall_no_timestamps():
    anchor = datetime(2024, 1, 15)
    docs = [Document(id="d1", text="", score=1.0, rank=1)]
    score = temporal_recall_at_k(docs, {"d1"}, k=1, query_anchor=anchor)
    assert score == 1.0  # no timestamp → weight=1.0 → same as standard recall


def test_bootstrap_ci_returns_bounds():
    scores = [0.5, 0.6, 0.55, 0.7, 0.45]
    low, high = bootstrap_ci(scores)
    assert low <= high
    assert 0.0 <= low <= 1.0


def test_paired_bootstrap_identical():
    scores = [0.5, 0.6, 0.55]
    p = paired_bootstrap_test(scores, scores)
    # Identical inputs → p-value should be high (no significant difference)
    assert p >= 0.5


def test_paired_bootstrap_different():
    a = [0.9] * 50
    b = [0.1] * 50
    p = paired_bootstrap_test(a, b)
    assert p < 0.05
