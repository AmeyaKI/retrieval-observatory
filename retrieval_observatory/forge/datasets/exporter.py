from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from retrieval_observatory.forge.types import SyntheticDataset


OutputFormat = Literal["beir", "custom"]


def export_dataset(
    dataset: SyntheticDataset,
    output_dir: str,
    fmt: OutputFormat = "beir",
) -> Path:
    """Export a SyntheticDataset to disk in the specified format.

    Args:
        dataset: The dataset to export.
        output_dir: Directory to write files into (created if absent).
        fmt: "beir" for BEIR-compatible format, "custom" for retobs native format.

    Returns:
        Path to the output directory.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if fmt == "beir":
        _export_beir(dataset, out)
    else:
        _export_custom(dataset, out)

    # Always write metadata
    meta_path = out / "forge_metadata.json"
    meta_path.write_text(json.dumps(dataset.summary(), indent=2), encoding="utf-8")

    return out


def _export_beir(dataset: SyntheticDataset, out: Path) -> None:
    """BEIR format: corpus.jsonl, queries.jsonl, qrels/test.tsv."""
    # corpus.jsonl — {"_id": ..., "text": ..., "title": ...}
    with open(out / "corpus.jsonl", "w", encoding="utf-8") as f:
        for doc_id, doc in dataset.corpus.items():
            record = {
                "_id": doc_id,
                "text": doc.get("text", ""),
                "title": doc.get("title", ""),
            }
            f.write(json.dumps(record) + "\n")

    # queries.jsonl — {"_id": ..., "text": ...}
    with open(out / "queries.jsonl", "w", encoding="utf-8") as f:
        for q in dataset.queries:
            record = {"_id": q.query_id, "text": q.text}
            f.write(json.dumps(record) + "\n")

    # qrels/test.tsv — TREC format: query_id \t 0 \t doc_id \t grade
    qrels_dir = out / "qrels"
    qrels_dir.mkdir(exist_ok=True)
    with open(qrels_dir / "test.tsv", "w", encoding="utf-8") as f:
        for query_id, doc_grades in dataset.qrels.items():
            for doc_id, grade in doc_grades.items():
                f.write(f"{query_id}\t0\t{doc_id}\t{grade}\n")


def _export_custom(dataset: SyntheticDataset, out: Path) -> None:
    """retobs custom format: corpus.jsonl, queries.jsonl, qrels.jsonl."""
    # corpus.jsonl — retobs custom format
    with open(out / "corpus.jsonl", "w", encoding="utf-8") as f:
        for doc_id, doc in dataset.corpus.items():
            record = {
                "id": doc_id,
                "text": doc.get("text", ""),
                "title": doc.get("title", ""),
            }
            f.write(json.dumps(record) + "\n")

    # queries.jsonl — retobs custom format with forge metadata fields
    with open(out / "queries.jsonl", "w", encoding="utf-8") as f:
        for q in dataset.queries:
            record = {
                "query_id": q.query_id,
                "text": q.text,
                "relevant_doc_ids": {doc_id: 2 for doc_id in q.positive_doc_ids},
                "metadata": {
                    "scenario_id": q.scenario_id,
                    "query_type": q.query_type,
                    "difficulty_label": q.difficulty_label,
                    "failure_category": q.failure_category,
                    "validated": q.validated,
                    **q.metadata,
                },
            }
            f.write(json.dumps(record) + "\n")

    # qrels.jsonl
    with open(out / "qrels.jsonl", "w", encoding="utf-8") as f:
        for query_id, doc_grades in dataset.qrels.items():
            for doc_id, grade in doc_grades.items():
                f.write(json.dumps({"query_id": query_id, "doc_id": doc_id, "grade": grade}) + "\n")
