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


def test_content_hash_stable_across_regenerated_forge_dataset():
    """Item 0: dataset_content_hash folds query_id into the fingerprint, so a Forge
    dataset regenerated from the same corpus must produce the same content_hash as the
    first generation -- this only holds now that Forge scenario/query ids are content-
    derived rather than random uuids (see forge/scenarios/*.py, forge/generation/*.py)."""
    from retrieval_observatory.forge.scenarios.temporal import TemporalScenarioDetector
    from retrieval_observatory.forge.generation.rule_based import generate_rule_based_queries

    corpus = {
        "doc1": {"text": "Apple released the iPhone in 2007.", "title": "iPhone 2007"},
        "doc2": {"text": "Apple introduced the iPhone 15 in 2023.", "title": "iPhone 2023"},
    }

    def _build_dataset():
        scenarios = TemporalScenarioDetector().detect(corpus)
        queries = []
        qrels = {}
        for scenario in scenarios:
            for q in generate_rule_based_queries(scenario, corpus, ["comparison"], n_per_type=1):
                queries.append({"query_id": q.query_id, "text": q.text})
                qrels[q.query_id] = {doc_id: 1 for doc_id in q.positive_doc_ids}
        return queries, qrels

    queries_a, qrels_a = _build_dataset()
    queries_b, qrels_b = _build_dataset()
    assert queries_a  # sanity: the fixture actually produced queries
    hash_a = dataset_content_hash(queries_a, qrels_a, corpus)
    hash_b = dataset_content_hash(queries_b, qrels_b, corpus)
    assert hash_a == hash_b
