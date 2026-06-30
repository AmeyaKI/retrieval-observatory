from datetime import datetime

import pytest

from retrieval_observatory.metrics.ranking import (
    average_precision,
    dedupe_preserve_rank,
    map_score,
    mrr,
    ndcg_at_k,
    ndcg_at_k_graded,
    precision_at_k,
)
from retrieval_observatory.metrics.comparison import paired_scores_by_query, pipeline_pairs
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.diagnostics import (
    build_query_diagnostics,
    compute_candidate_lineage,
    compute_churn_rate,
)
from retrieval_observatory.metrics.recall import recall_at_k, temporal_recall_at_k, temporal_recall_at_k_with_corpus
from retrieval_observatory.metrics.significance import bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


def test_recall_at_k_perfect():
    assert recall_at_k(["d1", "d2", "d3"], {"d1", "d2"}, k=3) == 1.0


def test_recall_at_k_partial():
    assert recall_at_k(["d1", "d4", "d5"], {"d1", "d2"}, k=3) == 0.5


def test_recall_at_k_zero():
    assert recall_at_k(["d3", "d4"], {"d1", "d2"}, k=2) == 0.0


def test_recall_at_k_empty_relevant():
    assert recall_at_k(["d1"], set(), k=1) == 0.0


def test_precision_at_k_perfect():
    assert precision_at_k(["d1", "d2", "d3"], {"d1", "d2"}, k=2) == 1.0


def test_precision_at_k_partial():
    assert precision_at_k(["d1", "d4", "d5"], {"d1", "d2"}, k=3) == pytest.approx(1 / 3)


def test_precision_at_k_zero():
    assert precision_at_k(["d3", "d4"], {"d1", "d2"}, k=2) == 0.0


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
        precision_at_k(["d1"], {"d1"}, k=0)
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


# ---------------------------------------------------------------------------
# M1: CandidateLineage and churn rate tests
# ---------------------------------------------------------------------------

def _make_doc(doc_id: str, rank: int = 1) -> Document:
    return Document(id=doc_id, text="", score=1.0, rank=rank)


def _make_snapshot(stage_index: int, stage_id: str, doc_ids: list) -> StageSnapshot:
    return StageSnapshot(
        stage_index=stage_index,
        stage_id=stage_id,
        documents=[_make_doc(did, i + 1) for i, did in enumerate(doc_ids)],
        latency_ms=1.0,
    )


def _make_result(pipeline_id: str, snapshots: list, query_id: str = "q1") -> PipelineResult:
    return PipelineResult(
        query_id=query_id,
        pipeline_id=pipeline_id,
        snapshots=snapshots,
        total_latency_ms=1.0,
        status="OK",
    )


def test_candidate_lineage_single_stage():
    result = _make_result("p1", [_make_snapshot(0, "bm25", ["d1", "d2", "d3"])])
    lineages = compute_candidate_lineage(result)
    assert len(lineages) == 1
    assert lineages[0].stage_index == 0
    assert set(lineages[0].entered) == {"d1", "d2", "d3"}
    assert lineages[0].survived == []
    assert lineages[0].dropped == []
    assert lineages[0].churn_rate == 0.0


def test_candidate_lineage_two_stages_no_churn():
    snaps = [
        _make_snapshot(0, "bm25", ["d1", "d2", "d3"]),
        _make_snapshot(1, "rerank", ["d1", "d2", "d3"]),
    ]
    result = _make_result("p1", snaps)
    lineages = compute_candidate_lineage(result)
    assert len(lineages) == 2
    assert lineages[1].churn_rate == 0.0
    assert set(lineages[1].survived) == {"d1", "d2", "d3"}
    assert lineages[1].dropped == []


def test_candidate_lineage_two_stages_with_churn():
    snaps = [
        _make_snapshot(0, "bm25", ["d1", "d2", "d3", "d4"]),
        _make_snapshot(1, "rerank", ["d1", "d5"]),  # d2,d3,d4 dropped; d5 new
    ]
    result = _make_result("p1", snaps)
    lineages = compute_candidate_lineage(result)
    stage1 = lineages[1]
    assert set(stage1.dropped) == {"d2", "d3", "d4"}
    assert set(stage1.survived) == {"d1"}
    assert set(stage1.entered) == {"d5"}
    assert stage1.churn_rate == pytest.approx(3 / 4)


def test_compute_churn_rate_single_stage():
    result = _make_result("p1", [_make_snapshot(0, "bm25", ["d1", "d2"])])
    lineages = compute_candidate_lineage(result)
    assert compute_churn_rate(lineages) == 0.0


def test_compute_churn_rate_multi_stage():
    snaps = [
        _make_snapshot(0, "bm25", ["d1", "d2", "d3", "d4"]),
        _make_snapshot(1, "rerank", ["d1", "d2"]),  # 2 dropped out of 4 → 0.5
    ]
    result = _make_result("p1", snaps)
    lineages = compute_candidate_lineage(result)
    assert compute_churn_rate(lineages) == pytest.approx(0.5)


def test_candidate_lineage_empty_snapshots():
    result = PipelineResult(
        query_id="q1", pipeline_id="p1", snapshots=[], total_latency_ms=0.0, status="OK"
    )
    lineages = compute_candidate_lineage(result)
    assert lineages == []


def test_diagnostics_include_churn_rate():
    snaps = [
        _make_snapshot(0, "bm25", ["d1", "d2", "d3"]),
        _make_snapshot(1, "rerank", ["d1", "d2"]),
    ]
    result = _make_result("p1", snaps)
    qrels = {"q1": {"d1": 2}}
    rows = build_query_diagnostics("run1", [result], qrels)
    assert len(rows) == 1
    assert "churn_rate" in rows[0]
    assert isinstance(rows[0]["churn_rate"], float)


@pytest.mark.asyncio
async def test_aggregate_keeps_branch_metrics_separate(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "branch_metrics.db"))
    await store.init_db()
    await store.save_run("run_branch", "branch-exp", "{}")
    await store.save_metric("run_branch", "p1", "q1", 0, "ndcg", 10, 0.4)
    await store.save_metric("run_branch", "p1", "q1", 0, "ndcg", 10, 0.2, branch_id="bm25_stage")

    engine = MetricsEngine()
    agg = await engine.aggregate("run_branch", store)
    assert "p1|stage0|ndcg@10" in agg
    assert "p1|stage0|ndcg@10|branch=bm25_stage" in agg
    assert agg["p1|stage0|ndcg@10"]["branch_id"] is None
    assert agg["p1|stage0|ndcg@10|branch=bm25_stage"]["branch_id"] == "bm25_stage"


# ---------------------------------------------------------------------------
# Accuracy & honesty fixes (added with fix pass)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_latency_percentile_rows_have_none_ci(tmp_path):
    """Fix 1: latency rows must carry None for ci_low/ci_high/std, not fake zero-width values."""
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=str(tmp_path / "lat_ci.db"))
    await store.init_db()
    await store.save_run("r1", "exp", "{}")
    # Write several latency values so the percentile aggregation fires
    for ms in [10.0, 20.0, 30.0]:
        await store.save_metric("r1", "p1", "q1", 0, "latency_ms", 0, ms)

    engine = MetricsEngine(latency_percentile_values=[50, 95])
    agg = await engine.aggregate("r1", store)

    latency_keys = [k for k in agg if "latency_p" in k]
    assert latency_keys, "Expected at least one latency_p* aggregation row"
    for k in latency_keys:
        row = agg[k]
        assert row["ci_low"] is None, f"{k}: ci_low should be None, got {row['ci_low']}"
        assert row["ci_high"] is None, f"{k}: ci_high should be None, got {row['ci_high']}"
        assert row["std"] is None, f"{k}: std should be None, got {row['std']}"


def test_ndcg_at_k_unchanged_after_dead_code_removal():
    """Fix 8: NDCG computation is correct after removing the dead ideal-DCG lines."""
    import math

    # Perfect ranking
    assert abs(ndcg_at_k(["d1", "d2"], {"d1", "d2"}, k=2) - 1.0) < 1e-9
    # Second-best ranking: relevant doc at rank 2, not rank 1
    dcg = 1.0 / math.log2(2 + 1)
    ideal = 1.0 / math.log2(1 + 1) + 1.0 / math.log2(2 + 1)
    expected = dcg / ideal
    assert abs(ndcg_at_k(["d3", "d1"], {"d1", "d2"}, k=2) - expected) < 1e-9


def test_expansion_stage_is_detected():
    """Fix 6: stages that grow the candidate set are labelled as expansion, churn_rate = 0."""
    snaps = [
        _make_snapshot(0, "retriever", ["d1", "d2"]),
        _make_snapshot(1, "expander", ["d1", "d2", "d3", "d4"]),  # candidate count grew
    ]
    result = _make_result("p1", snaps)
    lineages = compute_candidate_lineage(result)

    assert lineages[1].is_expansion is True
    assert lineages[1].churn_rate == 0.0
    assert set(lineages[1].entered) == {"d3", "d4"}


def test_expansion_stage_excluded_from_churn_rate():
    """Fix 6: compute_churn_rate ignores expansion stages."""
    snaps = [
        _make_snapshot(0, "retriever", ["d1", "d2", "d3", "d4"]),
        _make_snapshot(1, "expander", ["d1", "d2", "d3", "d4", "d5", "d6"]),
        _make_snapshot(2, "reranker", ["d1", "d2"]),  # 4/6 dropped → churn = 4/6
    ]
    result = _make_result("p1", snaps)
    lineages = compute_candidate_lineage(result)

    assert lineages[1].is_expansion is True
    assert lineages[2].is_expansion is False
    # Only the reranker stage (non-expansion) should contribute to churn rate
    assert compute_churn_rate(lineages) == pytest.approx(4 / 6)


def test_supports_filters_flag_on_adapters():
    """In-process BM25/HF and HTTP adapters declare filter support."""
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter
    from retrieval_observatory.adapters.hf_biencoder_adapter import HFBiEncoderAdapter
    from retrieval_observatory.adapters.http_adapter import HTTPAdapter
    from retrieval_observatory.adapters.langchain_adapter import LangChainAdapter
    from retrieval_observatory.adapters.llamaindex_adapter import LlamaIndexAdapter

    assert BM25Adapter.supports_filters is True
    assert HFBiEncoderAdapter.supports_filters is True
    assert LangChainAdapter.supports_filters is False
    assert LlamaIndexAdapter.supports_filters is False
    assert HTTPAdapter.supports_filters is True


def test_bm25_adapter_warns_on_filters(tmp_path):
    """BM25Adapter warns when unsupported filter keys are provided."""
    import warnings as _warnings
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter
    from retrieval_observatory.types import Query

    adapter = BM25Adapter(
        corpus={"d1": "hello world", "d2": "foo bar"},
        retriever_id="bm25_test",
    )
    q = Query(text="hello", k=1, query_id="q1", filters={"category": "news"})

    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        adapter.retrieve(q)

    assert any("unsupported keys" in str(w.message).lower() and issubclass(w.category, UserWarning) for w in caught)


def test_stage_contributions_include_n_pairs():
    """Fix 3: each delta in stage contributions includes n_pairs."""
    from retrieval_observatory.dashboard.api import _compute_stage_contributions

    metrics = {
        "bm25|stage0|recall@10": {
            "pipeline_id": "bm25",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.3,
            "branch_id": None,
        },
        "bm25__rerank|stage0|recall@10": {
            "pipeline_id": "bm25__rerank",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.2,
            "branch_id": None,
        },
        "bm25__rerank|stage1|recall@10": {
            "pipeline_id": "bm25__rerank",
            "stage_index": 1,
            "metric_name": "recall",
            "k": 10,
            "mean": 0.4,
            "branch_id": None,
        },
    }
    metrics_rows = [
        {"query_id": "q1", "pipeline_id": "bm25__rerank", "stage_index": 0, "branch_id": None, "metric_name": "recall", "k": 10, "value": 0.2},
        {"query_id": "q2", "pipeline_id": "bm25__rerank", "stage_index": 0, "branch_id": None, "metric_name": "recall", "k": 10, "value": 0.2},
        {"query_id": "q1", "pipeline_id": "bm25__rerank", "stage_index": 1, "branch_id": None, "metric_name": "recall", "k": 10, "value": 0.4},
        {"query_id": "q2", "pipeline_id": "bm25__rerank", "stage_index": 1, "branch_id": None, "metric_name": "recall", "k": 10, "value": 0.4},
    ]
    contributions = _compute_stage_contributions(metrics, metrics_rows)
    within = [c for c in contributions if c["comparison_tier"] == "within_pipeline_stage"]
    assert within, "Expected within_pipeline_stage contribution"
    for delta in within[0]["deltas"].values():
        assert "n_pairs" in delta, "n_pairs should be present in every delta"
        assert isinstance(delta["n_pairs"], int)
