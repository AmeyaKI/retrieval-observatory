import pytest

from retrieval_observatory.cli import _compare
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.store.sqlite import SQLiteStore


@pytest.mark.asyncio
async def test_compare_does_not_crash_on_latency_metrics_with_null_std(tmp_path, capsys):
    """Regression test: latency percentile metric rows always store std=None (bootstrap CI
    isn't meaningful for a single percentile point estimate -- see MetricsEngine.aggregate).
    `retobs compare` used `a.get('std', 0)`, which only falls back to the default when the
    key is *missing*, not when it's present with value None -- so formatting any latency
    metric with an f-string crashed every real `retobs compare` invocation.
    """
    db_path = str(tmp_path / "test.db")
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    await store.save_run("run1", "test", "{}")
    await store.save_run("run2", "test", "{}")

    metrics_rows = [
        {
            "run_id": run_id,
            "pipeline_id": "p1",
            "query_id": "q1",
            "stage_index": 0,
            "metric_name": "latency_ms",
            "k": 0,
            "value": 12.5,
            "branch_id": None,
            "query_metadata_json": None,
        }
        for run_id in ("run1", "run2")
    ]
    await store.save_metrics_batch(metrics_rows)

    engine = MetricsEngine()
    await engine.aggregate("run1", store)
    await engine.aggregate("run2", store)

    # Must not raise TypeError: unsupported format string passed to NoneType.__format__
    await _compare("run1", "run2", db_path)

    out = capsys.readouterr().out
    assert "Run Comparison" in out
    assert "12.5000" in out
