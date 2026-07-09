from __future__ import annotations

from retrieval_observatory.datasets.validation import dataset_content_hash, dataset_fingerprint


def _queries():
    return [{"query_id": "q1", "text": "hello world"}, {"query_id": "q2", "text": "foo bar"}]


def test_content_hash_is_stable_and_order_independent():
    q_forward = _queries()
    q_reversed = list(reversed(_queries()))
    qrels = {"q1": {"d1": 1}, "q2": {"d2": 1}}
    corpus = {"d1": "alpha", "d2": "beta"}
    assert dataset_content_hash(q_forward, qrels, corpus) == dataset_content_hash(q_reversed, qrels, corpus)


def test_content_hash_distinguishes_matching_counts_different_content():
    qrels = {"q1": {"d1": 1}, "q2": {"d2": 1}}
    a = dataset_content_hash(_queries(), qrels, {"d1": "alpha", "d2": "beta"})
    b = dataset_content_hash(_queries(), qrels, {"d1": "alpha", "d2": "DIFFERENT"})
    # Same counts, different corpus content -> different fingerprint (no collision).
    assert a != b


def test_fingerprint_includes_content_hash():
    fp = dataset_fingerprint("ds", _queries(), {"q1": {"d1": 1}}, {"d1": "alpha"})
    assert "content_hash" in fp
    assert len(fp["content_hash"]) == 64  # sha256 hexdigest
