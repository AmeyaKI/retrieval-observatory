"""Accuracy tests for hybrid (fan-in) pipelines.

Guards the must-resolve defect: a hybrid whose relevant doc is found by the dense arm
(not BM25) must NOT be mislabeled `candidate_miss`, because the pipeline succeeded.
"""
import pytest

import retrieval_observatory as ro

CORPUS = {"rel": "semantic match doc", "n1": "alpha", "n2": "beta", "n3": "gamma"}
QUERIES = [{"query_id": "q", "text": "find rel", "relevant_doc_ids": ["rel"]}]


@ro.retriever
def bm25_arm(query):
    return ["n1", "n2", "n3"]  # lexical arm misses the relevant doc


@ro.retriever
def dense_arm(query):
    return ["rel", "n1"]  # semantic arm finds it


@ro.reranker
def rerank(query, candidates):
    return [c.id for c in candidates][:3]


def _labels(report):
    return {lbl for d in report.diagnostics for lbl in d["failure_labels"]}


def test_fuse_stage0_contains_union_no_candidate_miss(tmp_path):
    rep = ro.benchmark(
        [ro.fuse([bm25_arm, dense_arm]), rerank],
        queries=QUERIES, corpus=CORPUS, k=3, db_path=str(tmp_path / "f.db"),
    )
    # stage 0 (fused) recall@5 should already be 1.0 — the union includes 'rel'.
    stage0 = next(v["mean"] for k, v in rep.metrics.items() if "stage0|recall@5" in k)
    assert stage0 == 1.0
    assert "candidate_miss" not in _labels(rep)


def test_nested_list_is_alias_for_fuse(tmp_path):
    rep = ro.benchmark(
        [[bm25_arm, dense_arm], rerank],
        queries=QUERIES, corpus=CORPUS, k=3, db_path=str(tmp_path / "n.db"),
    )
    assert "candidate_miss" not in _labels(rep)


def test_handrolled_fanin_emits_late_stage_recovery_not_candidate_miss(tmp_path):
    @ro.reranker
    def fuse_fake(query, candidates):
        return ["rel", "n1"]  # introduces 'rel' at stage 1, as a faked dense arm would

    rep = ro.benchmark(
        [bm25_arm, fuse_fake],
        queries=QUERIES, corpus=CORPUS, k=3, db_path=str(tmp_path / "h.db"),
    )
    labels = _labels(rep)
    assert "candidate_miss" not in labels  # the query SUCCEEDED — must not be inverted
    assert "late_stage_recovery" in labels


def test_true_candidate_miss_still_flagged(tmp_path):
    # No arm finds the relevant doc -> candidate_miss is still correct.
    rep = ro.benchmark(
        [ro.fuse([bm25_arm, bm25_arm])],
        queries=QUERIES, corpus=CORPUS, k=3, db_path=str(tmp_path / "m.db"),
    )
    assert "candidate_miss" in _labels(rep)


def test_fuse_requires_two_retrievers():
    with pytest.raises(ValueError):
        ro.fuse([bm25_arm])


def test_fuse_only_valid_at_stage0(tmp_path):
    with pytest.raises(ValueError):
        ro.benchmark(
            [bm25_arm, ro.fuse([bm25_arm, dense_arm])],
            queries=QUERIES, corpus=CORPUS, k=3, db_path=str(tmp_path / "e.db"),
        )
