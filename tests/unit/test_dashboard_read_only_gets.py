"""GET endpoints must never write: recomputed metrics stay out of the store on a read-only
registry, and metric rows are deduplicated on their natural key."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

RUN = "run1"


def _trace(query_id: str) -> RetrievalTrace:
    source = OperatorSpan(
        "source", "SOURCE", "source", (), "FIRED", 3.0,
        outputs=(Candidate(doc_id="d1", score=1.0, rank=1), Candidate(doc_id="d2", score=0.5, rank=2)),
        replay_policy="EXACT",
    )
    return RetrievalTrace(
        trace_id=f"t-{query_id}", service_id="bench", run_id=RUN, query_id=query_id, query_text="q",
        pipeline_id="bm25", spans=(source,), final_op_ids=("source",),
        timing=TraceTiming(wall_clock_ms=3.0, critical_path_ms=3.0, operator_sum_ms=3.0),
    )


async def _seed(db_path: Path, *, with_metrics: bool) -> None:
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run(RUN, "exp", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_qrels(RUN, {f"q{i}": {"d1": 1} for i in range(5)})
    await store.save_traces([_trace(f"q{i}") for i in range(5)])
    if with_metrics:
        for i in range(5):
            await store.save_metric(RUN, "bm25", f"q{i}", 0, "recall", 10, 1.0)
    await store.finish_run(RUN)


def _count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


@pytest.mark.asyncio
async def test_read_only_metrics_get_computes_without_persisting(tmp_path: Path) -> None:
    db_path = tmp_path / "ro.db"
    await _seed(db_path, with_metrics=False)
    assert _count(db_path, "metric_scores") == 0
    registry = DbRegistry([str(db_path)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    response = client.get(f"/dbs/{registry.default_db_id}/runs/{RUN}/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(entry["metric_name"] == "recall" and entry["k"] == 10 for entry in body.values())
    assert _count(db_path, "metric_scores") == 0, "a GET on a read-only registry must not write metric rows"


@pytest.mark.asyncio
async def test_save_metrics_batch_ignores_duplicate_natural_keys(tmp_path: Path) -> None:
    store = SQLiteStore(str(tmp_path / "dedup.db"))
    await store.init_db()
    rows = [
        {"run_id": RUN, "pipeline_id": "bm25", "query_id": "q1", "stage_index": 0, "metric_name": "recall", "k": 10, "value": 1.0},
        {"run_id": RUN, "pipeline_id": "bm25", "query_id": "q1", "stage_index": 0, "metric_name": "recall", "k": 10, "value": 1.0, "branch_id": "arm"},
    ]
    await store.save_metrics_batch(rows)
    await store.save_metrics_batch(rows)
    stored = await store.get_metrics(RUN)
    assert len(stored) == 2
    assert {row.get("branch_id") for row in stored} == {None, "arm"}


@pytest.mark.asyncio
async def test_investigation_get_does_not_write(tmp_path: Path) -> None:
    db_path = tmp_path / "inv.db"
    await _seed(db_path, with_metrics=False)
    before = db_path.read_bytes()
    registry = DbRegistry([str(db_path)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    for path in (f"/runs/{RUN}/queries", f"/runs/{RUN}/queries/q1", f"/runs/{RUN}/documents", f"/runs/{RUN}/projection"):
        response = client.get(f"/dbs/{registry.default_db_id}/investigation{path}")
        assert response.status_code == 200, response.text
    body = client.get(f"/dbs/{registry.default_db_id}/investigation/runs/{RUN}/queries").json()
    assert body["rows"] == [] and {f["code"] for f in body["findings"]} >= {"projection_unavailable"}
    assert _count(db_path, "investigation_pairs") == 0
    assert db_path.read_bytes() == before, "investigation GETs on a read-only registry must not write"
