"""Postgres store tests — skipped unless RETOBS_POSTGRES_DSN is set."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RETOBS_POSTGRES_DSN"),
    reason="RETOBS_POSTGRES_DSN not set — skipping Postgres tests",
)


@pytest.mark.asyncio
async def test_postgres_roundtrip():
    from retrieval_observatory.store.postgres import PostgresStore
    from retrieval_observatory.types import Document, PipelineResult, StageSnapshot

    store = PostgresStore(dsn=os.environ["RETOBS_POSTGRES_DSN"])
    await store.init_db()

    docs = [Document(id="pg_d1", text="hello", score=0.9, rank=1)]
    snap = StageSnapshot(stage_index=0, stage_id="r1", documents=docs, latency_ms=8.0)
    result = PipelineResult(
        query_id="pg_q1",
        pipeline_id="pg_p1",
        snapshots=[snap],
        total_latency_ms=8.0,
        status="OK",
    )

    await store.save_run("pg_run1", "pg-test", "{}")
    await store.save_result("pg_run1", result)

    retrieved = await store.get_results("pg_run1")
    assert any(r.query_id == "pg_q1" for r in retrieved)
    assert any(
        r.snapshots[0].documents[0].id == "pg_d1"
        for r in retrieved
        if r.query_id == "pg_q1"
    )

    await store.cache_set("pg_key", '{"ok": true}')
    assert await store.cache_get("pg_key") == '{"ok": true}'
    assert await store.cache_get("missing") is None

    await store.close()
