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
