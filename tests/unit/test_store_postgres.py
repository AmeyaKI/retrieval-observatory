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


@pytest.mark.asyncio
async def test_postgres_forge_trace_lineage_roundtrip():
    from retrieval_observatory.store.postgres import PostgresStore

    store = PostgresStore(dsn=os.environ["RETOBS_POSTGRES_DSN"])
    await store.init_db()

    import json

    await store.save_forge_dataset("pg_ds", json.dumps({"n_queries": 1}), "/c", "/out")
    await store.save_forge_queries("pg_ds", json.dumps([{
        "query_id": "pg_fq", "text": "test", "scenario_id": "s1",
        "query_type": "paraphrase", "difficulty_label": "medium",
    }]))
    await store.save_golden_set("pg_golden", json.dumps([{"query_id": "q1", "text": "hi", "relevant_doc_ids": []}]))
    assert await store.get_golden_set("pg_golden") is not None
    assert await store.list_golden_sets()

    from retrieval_observatory.tracing.types import RetrievalTrace
    from retrieval_observatory.types import StageSnapshot, Document

    t = RetrievalTrace(
        trace_id="pg_t1", service="pg_svc", query_id="q", query_text="hello",
        pipeline_id="p", snapshots=[StageSnapshot(0, "s", [Document("d", "", 0.5, 1)], 1.0)],
        total_latency_ms=1.0, predicted_difficulty="medium", suspected_failures=["candidate_miss"],
    )
    await store.save_trace(t)
    assert await store.list_services()
    rows = await store.list_traces("pg_svc")
    assert rows
    assert await store.get_trace("pg_t1")

    lineage = await store.get_query_lineage("pg_fq")
    assert lineage["origin"]["source"] == "forge"

    await store.close()


@pytest.mark.asyncio
async def test_postgres_reliability_snapshot_roundtrip():
    from retrieval_observatory.store.postgres import PostgresStore

    store = PostgresStore(dsn=os.environ["RETOBS_POSTGRES_DSN"])
    await store.init_db()

    await store.save_reliability_snapshot(
        "pg_run_rel",
        0.82,
        {"recall10": 0.75, "latency_p50": 120.0},
    )
    history = await store.get_reliability_history(run_id="pg_run_rel", limit=5)
    assert history
    assert history[0]["run_id"] == "pg_run_rel"
    assert history[0]["value"] == pytest.approx(0.82)
    assert history[0]["components"]["recall10"] == pytest.approx(0.75)

    await store.close()
