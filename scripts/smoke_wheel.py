from __future__ import annotations

import tempfile
from pathlib import Path

import retrieval_observatory as ro


CORPUS = {"d1": "hybrid retrieval combines lexical and dense search", "d2": "rerankers rescore candidates"}
QUERIES = [{"query_id": "q1", "text": "lexical dense hybrid"}]
QRELS = {"q1": {"d1": 1}}


def retrieve(_: str) -> list[str]:
    return ["d1", "d2"]


with tempfile.TemporaryDirectory() as directory:
    db = str(Path(directory) / "smoke.db")
    report = ro.evaluate(retrieve, queries=QUERIES, corpus=CORPUS, qrels=QRELS, db_path=db)
    assert report.run_id
    assert report.report.kind == "run"
    evidence = ro.inspect_query(report.run_id, "q1", db_path=db)
    assert evidence["scope"]["run_id"] == report.run_id
    assert evidence["ground_truth"]["relevant_doc_ids"] == ["d1"]
    print(f"Wheel callable smoke passed: {report.run_id}")
