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
    assert len(fp["query_hash"]) == 64
    assert len(fp["qrel_hash"]) == 64
    assert len(fp["corpus_hash"]) == 64


def test_content_hash_stable_across_independently_built_equal_datasets():
    """Two datasets with the same content but different insertion order hash identically."""

    def _build(reverse: bool):
        items = [("q1", "hello world", {"d1": 1, "d2": 0}), ("q2", "foo bar", {"d2": 2})]
        docs = [("d1", "alpha"), ("d2", "beta")]
        if reverse:
            items, docs = list(reversed(items)), list(reversed(docs))
        queries = [{"query_id": qid, "text": text} for qid, text, _ in items]
        qrels = {qid: dict(reversed(list(rels.items())) if reverse else rels) for qid, _, rels in items}
        corpus = dict(docs)
        return queries, qrels, corpus

    a = dataset_content_hash(*_build(reverse=False))
    b = dataset_content_hash(*_build(reverse=True))
    assert a == b
    fp_a = dataset_fingerprint("ds", *_build(reverse=False))
    fp_b = dataset_fingerprint("ds", *_build(reverse=True))
    assert fp_a == fp_b


def test_fingerprint_query_input_hash_tracks_metadata_while_query_hash_does_not():
    plain = [{"query_id": "q1", "text": "hello world"}, {"query_id": "q2", "text": "foo bar"}]
    tagged = [{"query_id": "q1", "text": "hello world", "metadata": {"segment": "gold"}}, {"query_id": "q2", "text": "foo bar"}]
    qrels = {"q1": {"d1": 1}, "q2": {"d2": 0}}
    corpus = {"d1": "alpha", "d2": "beta"}
    fp_plain = dataset_fingerprint("ds", plain, qrels, corpus)
    fp_tagged = dataset_fingerprint("ds", tagged, qrels, corpus)
    assert fp_plain["query_hash"] == fp_tagged["query_hash"]
    assert fp_plain["content_hash"] == fp_tagged["content_hash"]
    assert fp_plain["query_input_hash"] != fp_tagged["query_input_hash"]
    assert len(fp_plain["query_input_hash"]) == 64
    assert len(fp_plain["judgment_digest"]) == 64
    assert fp_plain["judgment_digest"] == fp_tagged["judgment_digest"]
    assert fp_plain["judgment_schema_version"] == 1
    # The judgment digest tracks grades, including an explicit zero becoming a one.
    assert dataset_fingerprint("ds", plain, {"q1": {"d1": 1}, "q2": {"d2": 1}}, corpus)["judgment_digest"] != fp_plain["judgment_digest"]
