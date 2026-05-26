import os
import tempfile

import pytest

from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SQLiteStore(db_path=db_path)
    await s.init_db()
    return s


@pytest.mark.asyncio
async def test_save_and_get_result(store):
    docs = [Document(id="d1", text="hello", score=0.9, rank=1)]
    snap = StageSnapshot(stage_index=0, stage_id="r1", documents=docs, latency_ms=12.5)
    result = PipelineResult(
        query_id="q1",
        pipeline_id="p1",
        snapshots=[snap],
        total_latency_ms=12.5,
        status="OK",
    )

    await store.save_run("run1", "test-experiment", "{}")
    await store.save_result("run1", result)

    retrieved = await store.get_results("run1")
    assert len(retrieved) == 1
    assert retrieved[0].query_id == "q1"
    assert retrieved[0].pipeline_id == "p1"
    assert retrieved[0].snapshots[0].documents[0].id == "d1"
    assert retrieved[0].snapshots[0].stage_id == "r1"


@pytest.mark.asyncio
async def test_save_and_get_metric(store):
    await store.save_run("run1", "test-experiment", "{}")
    await store.save_metric("run1", "p1", "q1", 0, "recall", 10, 0.75)

    metrics = await store.get_metrics("run1")
    assert len(metrics) == 1
    assert metrics[0]["metric_name"] == "recall"
    assert metrics[0]["value"] == 0.75


@pytest.mark.asyncio
async def test_save_result_with_empty_snapshots_persists_envelope(store):
    result = PipelineResult(
        query_id="q_timeout",
        pipeline_id="p_timeout",
        snapshots=[],
        total_latency_ms=250.0,
        status="TIMEOUT",
    )
    await store.save_run("run1", "test-experiment", "{}")
    await store.save_result("run1", result)

    retrieved = await store.get_results("run1")
    assert len(retrieved) == 1
    assert retrieved[0].status == "TIMEOUT"
    assert retrieved[0].total_latency_ms == 250.0
    assert retrieved[0].snapshots == []


@pytest.mark.asyncio
async def test_cache_roundtrip(store):
    await store.cache_set("key123", '{"test": true}')
    result = await store.cache_get("key123")
    assert result == '{"test": true}'


@pytest.mark.asyncio
async def test_cache_miss(store):
    result = await store.cache_get("nonexistent_key")
    assert result is None


@pytest.mark.asyncio
async def test_list_runs(store):
    await store.save_run("run1", "exp1", "{}")
    await store.save_run("run2", "exp2", "{}")
    runs = await store.list_runs()
    run_ids = [r["run_id"] for r in runs]
    assert "run1" in run_ids
    assert "run2" in run_ids
