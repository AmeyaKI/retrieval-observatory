"""Queries, corpus and qrels as ``retobs evaluate`` reads them: from JSON/JSONL files or the target module."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def read_json_records(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    # A one-line JSONL file parses as a single object; it is still one record, as is a query or
    # judgment row in a ``.json`` file. Any other ``.json`` object is a mapping (doc id -> text, ...).
    if isinstance(parsed, dict) and (path.suffix.lower() == ".jsonl" or "query_id" in parsed or "doc_id" in parsed):
        return [parsed]
    return parsed


def evaluate_inputs(module, queries_path: Optional[Path], corpus_path: Optional[Path], qrels_path: Optional[Path]):
    queries = read_json_records(queries_path) if queries_path else getattr(module, "QUERIES", getattr(module, "queries", None))
    corpus_raw = read_json_records(corpus_path) if corpus_path else getattr(module, "CORPUS", getattr(module, "corpus", None))
    qrels_raw = read_json_records(qrels_path) if qrels_path else getattr(module, "QRELS", getattr(module, "qrels", None))
    if isinstance(corpus_raw, list):
        corpus = {
            str(row.get("id", row.get("doc_id"))): str(row.get("text", row.get("content", "")))
            for row in corpus_raw
        }
    else:
        corpus = corpus_raw
    if isinstance(qrels_raw, list):
        qrels = {}
        for row in qrels_raw:
            if not (isinstance(row, dict) and row.get("query_id")):
                continue
            if "doc_id" in row:  # one judged pair per row: {query_id, doc_id, relevance}
                graded = qrels.setdefault(str(row["query_id"]), {})
                if isinstance(graded, dict):
                    graded[str(row["doc_id"])] = int(row.get("relevance", 1))
            else:
                qrels[str(row["query_id"])] = row.get("relevant_doc_ids", row.get("qrels", {}))
    else:
        qrels = qrels_raw
    if not queries or not corpus:
        raise ValueError(
            "Evaluation needs queries and corpus. Pass --queries/--corpus JSON(L), "
            "or define QUERIES and CORPUS in the target module."
        )
    return queries, corpus, qrels
