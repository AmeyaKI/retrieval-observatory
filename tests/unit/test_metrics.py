from datetime import datetime, timedelta

import pytest

from retrieval_observatory.metrics.ranking import average_precision, dedupe_preserve_rank, map_score, mrr, ndcg_at_k, ndcg_at_k_graded
from retrieval_observatory.metrics.comparison import paired_scores_by_query, pipeline_pairs
from retrieval_observatory.metrics.diagnostics import build_query_diagnostics
from retrieval_observatory.metrics.recall import recall_at_k, temporal_recall_at_k, temporal_recall_at_k_with_corpus
from retrieval_observatory.metrics.significance import bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


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


def test_temporal_recall_uses_corpus_timestamp_for_unretrieved_relevant_docs():
    anchor = datetime(2024, 1, 15)
    retrieved = [
        Document(id="old", text="", score=1.0, rank=1, timestamp=datetime(2023, 1, 1)),
    ]
    corpus = {
        "old": Document(id="old", text="", score=0.0, rank=0, timestamp=datetime(2023, 1, 1)),
        "recent": Document(id="recent", text="", score=0.0, rank=0, timestamp=datetime(2024, 1, 14)),
    }

    score = temporal_recall_at_k_with_corpus(
        retrieved,
        {"old", "recent"},
        k=1,
        query_anchor=anchor,
        corpus_documents=corpus,
    )

    assert score < 0.5


def test_dedupe_preserve_rank():
    assert dedupe_preserve_rank(["d1", "d1", "d2", "d1", "d3"]) == ["d1", "d2", "d3"]


def test_ndcg_graded_basic():
    score = ndcg_at_k_graded(["d2", "d1"], {"d1": 3, "d2": 1}, k=2)
    assert 0.0 <= score <= 1.0


def test_metric_k_must_be_positive():
    with pytest.raises(ValueError):
        recall_at_k(["d1"], {"d1"}, k=0)
    with pytest.raises(ValueError):
        ndcg_at_k(["d1"], {"d1"}, k=-1)
    with pytest.raises(ValueError):
        temporal_recall_at_k(
            [Document(id="d1", text="", score=1.0, rank=1)],
            {"d1"},
            k=0,
            query_anchor=datetime(2024, 1, 15),
        )


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


def test_paired_scores_join_by_query_id_not_row_order():
    a = [
        {"pipeline_id": "p", "stage_index": 0, "metric_name": "recall", "k": 10, "query_id": "q1", "value": 0.1},
        {"pipeline_id": "p", "stage_index": 0, "metric_name": "recall", "k": 10, "query_id": "q2", "value": 0.9},
    ]
    b = [
        {"pipeline_id": "p", "stage_index": 0, "metric_name": "recall", "k": 10, "query_id": "q2", "value": 0.8},
        {"pipeline_id": "p", "stage_index": 0, "metric_name": "recall", "k": 10, "query_id": "q1", "value": 0.2},
    ]

    s1, s2, n = paired_scores_by_query(a, b, "p|stage0|recall@10")
    assert n == 2
    assert s1 == [0.1, 0.9]
    assert s2 == [0.2, 0.8]


def test_query_diagnostics_labels_reranker_drop():
    result = PipelineResult(
        query_id="q1",
        pipeline_id="bm25__rerank",
        status="OK",
        total_latency_ms=3.0,
        snapshots=[
            StageSnapshot(
                stage_index=0,
                stage_id="bm25",
                documents=[Document(id="d1", text="", score=1.0, rank=1)],
                latency_ms=1.0,
            ),
            StageSnapshot(
                stage_index=1,
                stage_id="rerank",
                documents=[Document(id="d2", text="", score=1.0, rank=1)],
                latency_ms=2.0,
            ),
        ],
    )

    rows = build_query_diagnostics("run1", [result], {"q1": {"d1": 1}})
    assert rows[0]["failure_labels"] == ["reranker_drop"]
    assert rows[0]["missing_relevant_ids"] == ["d1"]


def test_pipeline_pairs_basic():
    ids = ["bm25", "bm25__rerank"]
    assert pipeline_pairs(ids) == [("bm25", "bm25__rerank")]


def test_pipeline_pairs_three_stage():
    ids = ["bm25", "bm25__rerank", "bm25__rerank__cohere"]
    result = pipeline_pairs(ids)
    assert ("bm25", "bm25__rerank") in result
    assert ("bm25__rerank", "bm25__rerank__cohere") in result
    assert len(result) == 2


def test_pipeline_pairs_no_prefix_match():
    ids = ["bm25", "dense", "rrf"]
    assert pipeline_pairs(ids) == []


def test_pipeline_pairs_partial_match_only():
    # "bm25__rerank" exists but "bm25" does not — no pair
    ids = ["bm25__rerank", "dense"]
    assert pipeline_pairs(ids) == []


def test_pipeline_pairs_preserves_order():
    ids = ["bm25", "dense", "bm25__rerank", "dense__rerank"]
    result = pipeline_pairs(ids)
    assert ("bm25", "bm25__rerank") in result
    assert ("dense", "dense__rerank") in result
    assert len(result) == 2


def test_benjamini_hochberg_empty():
    from retrieval_observatory.metrics.significance import benjamini_hochberg
    assert benjamini_hochberg([]) == []


def test_benjamini_hochberg_single():
    from retrieval_observatory.metrics.significance import benjamini_hochberg
    result = benjamini_hochberg([0.001])
    assert len(result) == 1
    assert result[0] == pytest.approx(0.001)


def test_benjamini_hochberg_two_significant():
    from retrieval_observatory.metrics.significance import benjamini_hochberg
    result = benjamini_hochberg([0.04, 0.04])
    assert all(q < 0.05 for q in result)
