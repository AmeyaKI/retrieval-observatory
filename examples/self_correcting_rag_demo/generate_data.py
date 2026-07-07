#!/usr/bin/env python3
"""Generate the tiny corpus and queries for the self-correcting RAG demo."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent

DOCS = [
    ("d1", "Automobile vehicle listings for local dealerships."),
    ("d2", "Physician gp appointment scheduling system."),
    ("d3", "Quick rapid delivery service for urgent packages."),
    ("d4", "Affordable inexpensive furniture for small apartments."),
    ("d5", "Soil pH testing helps gardening tips succeed for small yards."),
]

QUERIES = [
    ("q1", "Where can I buy a cheap car", ["d1", "d4"]),
    ("q2", "I need to see a doctor fast", ["d2", "d3"]),
    ("q3", "What soil pH and gardening tips should I use", ["d5"]),
]


def main() -> None:
    with (OUT / "corpus.jsonl").open("w") as f:
        for doc_id, text in DOCS:
            f.write(json.dumps({"id": doc_id, "text": text}) + "\n")

    with (OUT / "queries.jsonl").open("w") as f:
        for qid, text, rel in QUERIES:
            f.write(json.dumps({"query_id": qid, "text": text, "relevant_doc_ids": rel}) + "\n")

    print(f"Wrote {len(DOCS)} docs and {len(QUERIES)} queries to {OUT}")


if __name__ == "__main__":
    main()
