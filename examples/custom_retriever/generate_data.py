#!/usr/bin/env python3
"""Generate a tiny corpus and queries for the custom retriever demo."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent

DOCS = [
    ("d1", "BM25 sparse retrieval uses term frequency for ranking."),
    ("d2", "Dense retrieval uses neural embeddings for semantic search."),
    ("d3", "Hybrid retrieval combines sparse and dense scores with fusion."),
    ("d4", "Cross-encoder rerankers improve precision at the top of the list."),
    ("d5", "Recall at K measures how many relevant documents appear in the top K."),
    ("d6", "NDCG rewards ranking relevant documents near the top."),
    ("d7", "Multi-stage pipelines chain a retriever with one or more rerankers."),
    ("d8", "Latency budgets trade retrieval quality against response time."),
]

QUERIES = [
    ("q1", "What is BM25 sparse retrieval?", ["d1"]),
    ("q2", "How does dense embedding retrieval work?", ["d2"]),
    ("q3", "Explain hybrid sparse and dense retrieval.", ["d3"]),
    ("q4", "What does a cross-encoder reranker do?", ["d4"]),
    ("q5", "What is recall at K?", ["d5"]),
    ("q6", "How is NDCG used in evaluation?", ["d6"]),
    ("q7", "What is a multi-stage retrieval pipeline?", ["d7"]),
    ("q8", "Why do latency budgets matter?", ["d8"]),
]


def main() -> None:
    with (OUT / "corpus.jsonl").open("w") as f:
        for doc_id, text in DOCS:
            f.write(json.dumps({"id": doc_id, "text": text}) + "\n")

    with (OUT / "queries.jsonl").open("w") as f:
        for qid, text, rel in QUERIES:
            f.write(
                json.dumps(
                    {"query_id": qid, "text": text, "relevant_doc_ids": rel}
                )
                + "\n"
            )

    print(f"Wrote {len(DOCS)} docs and {len(QUERIES)} queries to {OUT}")


if __name__ == "__main__":
    main()
