"""P1.1 — the config-dict SDK seam that REST and MCP both call."""
import os

import pytest

from retrieval_observatory.sdk import run_from_config

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _bm25_config(db_path: str) -> dict:
    return {
        "experiment": {"name": "unit-run-from-config"},
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
        "output": {"store": "sqlite", "db_path": db_path},
    }


def test_run_from_config_produces_metrics(tmp_path):
    db_path = str(tmp_path / "results.db")
    report = run_from_config(_bm25_config(db_path), max_queries=5)
    assert report.run_id
    assert report.metrics, "expected non-empty aggregated metrics"
    # Every aggregate entry carries a bootstrap CI.
    sample = next(iter(report.metrics.values()))
    assert "ci_low" in sample and "ci_high" in sample


@pytest.mark.asyncio
async def test_run_from_config_max_queries_cap(tmp_path):
    from retrieval_observatory.store.sqlite import SQLiteStore

    db_path = str(tmp_path / "capped.db")
    report = run_from_config(_bm25_config(db_path), max_queries=2)
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    rows = await store.get_run_queries(report.run_id)
    assert len(rows) == 2


def test_run_from_config_rejects_empty_pipelines(tmp_path):
    cfg = _bm25_config(str(tmp_path / "x.db"))
    cfg["pipelines"] = []
    with pytest.raises(ValueError):
        run_from_config(cfg, max_queries=2)
