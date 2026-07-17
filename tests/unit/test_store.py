
import pytest

from retrieval_observatory.store.sqlite import SQLiteStore


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SQLiteStore(db_path=db_path)
    await s.init_db()
    return s


@pytest.mark.asyncio
async def test_save_and_get_metric(store):
    await store.save_run("run1", "test-experiment", "{}")
    await store.save_metric("run1", "p1", "q1", 0, "recall", 10, 0.75)

    metrics = await store.get_metrics("run1")
    assert len(metrics) == 1
    assert metrics[0]["metric_name"] == "recall"
    assert metrics[0]["value"] == 0.75


@pytest.mark.asyncio
async def test_save_and_get_qrels_roundtrip(store):
    await store.save_run("run1", "test-experiment", "{}")
    qrels = {"q1": {"doc_a": 1, "doc_b": 2}, "q2": {"doc_c": 1}}

    await store.save_qrels("run1", qrels)

    assert await store.get_qrels("run1") == qrels


@pytest.mark.asyncio
async def test_get_qrels_missing_run_returns_empty_dict(store):
    assert await store.get_qrels("no-such-run") == {}


@pytest.mark.asyncio
async def test_save_qrels_overwrites_existing(store):
    await store.save_run("run1", "test-experiment", "{}")
    await store.save_qrels("run1", {"q1": {"doc_a": 1}})
    await store.save_qrels("run1", {"q1": {"doc_b": 1}})

    assert await store.get_qrels("run1") == {"q1": {"doc_b": 1}}


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
