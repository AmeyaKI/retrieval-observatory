from __future__ import annotations

from retrieval_observatory.datasets.inmemory import InMemoryDataset


def test_content_stable_id_for_string_queries():
    # Item 0: two separate calls with the same query text (e.g. two runs against the same
    # in-memory list) must produce the same fallback query_id -- unlike the old positional
    # f"q{i}" fallback, which aliases unrelated queries whenever the list is reordered.
    ds_a = InMemoryDataset(["what is retrieval", "how does fusion work"])
    ds_b = InMemoryDataset(["how does fusion work", "what is retrieval"])  # reordered
    queries_a, _ = ds_a.load()
    queries_b, _ = ds_b.load()
    id_by_text_a = {q.text: q.query_id for q in queries_a}
    id_by_text_b = {q.text: q.query_id for q in queries_b}
    assert id_by_text_a == id_by_text_b


def test_content_stable_id_for_dict_queries_without_explicit_id():
    ds = InMemoryDataset([{"text": "same question"}, {"text": "same question"}])
    queries, _ = ds.load()
    # Duplicate text within one batch gets unique ids (tie-broken), not a collision.
    assert queries[0].query_id != queries[1].query_id


def test_explicit_query_id_still_respected():
    ds = InMemoryDataset([{"text": "hello", "query_id": "custom_1"}])
    queries, _ = ds.load()
    assert queries[0].query_id == "custom_1"


def test_qrels_keyed_by_stable_id_across_two_calls():
    items = [{"text": "q1 text", "relevant_doc_ids": ["d1"]}]
    ds_a = InMemoryDataset(items)
    ds_b = InMemoryDataset(items)
    _, qrels_a = ds_a.load()
    _, qrels_b = ds_b.load()
    assert set(qrels_a.keys()) == set(qrels_b.keys())
