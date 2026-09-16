import json

from retrieval_observatory.datasets.custom import CustomDataset


def test_custom_dataset_preserves_query_and_corpus_metadata(tmp_path):
    queries_path = tmp_path / "queries.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    qrels_path = tmp_path / "qrels.jsonl"

    queries_path.write_text(
        json.dumps(
            {
                "query_id": "q1",
                "text": "fresh policy",
                "metadata": {"tenant": "acme"},
                "tags": ["temporal"],
                "relevant_doc_ids": {"d1": 2},
                "temporal_anchor": "2024-01-03T00:00:00",
            }
        )
        + "\n"
    )
    corpus_path.write_text(
        json.dumps(
            {
                "id": "d1",
                "title": "Policy",
                "text": "fresh policy text",
                "timestamp": "2024-01-02T00:00:00",
                "source": "handmade",
            }
        )
        + "\n"
    )
    qrels_path.write_text(json.dumps({"query_id": "q1", "doc_id": "d2", "grade": 1}) + "\n")

    dataset = CustomDataset(
        queries_path=str(queries_path),
        corpus_path=str(corpus_path),
        qrels_path=str(qrels_path),
        metadata_fields=["source"],
    )
    queries, qrels = dataset.load()

    assert queries[0].metadata["tenant"] == "acme"
    assert queries[0].metadata["tags"] == ["temporal"]
    assert qrels["q1"] == {"d2": 1}
    assert dataset.corpus_documents["d1"].title == "Policy"
    assert dataset.corpus_documents["d1"].metadata["source"] == "handmade"
    assert dataset.corpus_documents["d1"].timestamp is not None


def test_custom_dataset_stringifies_integer_ids(tmp_path):
    """Integer query/doc ids in the queries file must join with the (string) corpus and qrels ids."""
    queries_path = tmp_path / "q.jsonl"
    corpus_path = tmp_path / "c.jsonl"
    qrels_path = tmp_path / "r.jsonl"
    queries_path.write_text(
        json.dumps({"query_id": 1, "text": "apple", "relevant_doc_ids": [10]}) + "\n"
        + json.dumps({"query_id": 2, "text": "pear", "relevant_doc_ids": {11: 2}}) + "\n"
    )
    corpus_path.write_text(json.dumps({"id": 10, "text": "apple pie"}) + "\n" + json.dumps({"id": 11, "text": "pear"}) + "\n")
    qrels_path.write_text(json.dumps({"query_id": 1, "doc_id": 10, "grade": 2}) + "\n")

    queries, qrels = CustomDataset(str(queries_path), str(corpus_path)).load()
    assert [q.query_id for q in queries] == ["1", "2"]
    assert qrels == {"1": {"10": 1}, "2": {"11": 2}}
    assert all(doc_id in CustomDataset(str(queries_path), str(corpus_path)).corpus for doc_id in qrels["1"])

    queries, qrels = CustomDataset(str(queries_path), str(corpus_path), str(qrels_path)).load()
    assert qrels[queries[0].query_id] == {"10": 2}
