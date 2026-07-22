"""Postgres store tests; live round trips require RETOBS_POSTGRES_DSN."""
import os

import pytest

from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.postgres import PostgresStore


requires_postgres = pytest.mark.skipif(
    not os.getenv("RETOBS_POSTGRES_DSN"),
    reason="RETOBS_POSTGRES_DSN not set — skipping Postgres tests",
)


@requires_postgres
@pytest.mark.asyncio
async def test_postgres_roundtrip():
    from retrieval_observatory.store.postgres import PostgresStore
    from retrieval_observatory.store.base import TraceQuery
    from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace

    store = PostgresStore(dsn=os.environ["RETOBS_POSTGRES_DSN"])
    await store.init_db()

    trace = RetrievalTrace(
        trace_id="pg-trace",
        service_id="pg-service",
        run_id="pg_run1",
        query_id="pg_q1",
        pipeline_id="pg_p1",
        query_text="query",
        spans=(OperatorSpan.source("r1", "Source", ()),),
        final_op_ids=("r1",),
    )

    await store.save_run("pg_run1", "pg-test", "{}")
    await store.save_trace(trace)
    retrieved = await store.list_traces(TraceQuery(run_id="pg_run1"))
    assert [item.trace_id for item in retrieved] == ["pg-trace"]

    await store.cache_set("pg_key", '{"ok": true}')
    assert await store.cache_get("pg_key") == '{"ok": true}'
    assert await store.cache_get("missing") is None

    await store.close()


@requires_postgres
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

    from retrieval_observatory.store.base import TraceQuery
    from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

    t = RetrievalTrace(
        trace_id="pg_t1", service_id="pg_svc", run_id=None, query_id="q", query_text="hello",
        pipeline_id="p", spans=(OperatorSpan.source("s", "Source", (Candidate("d", 0.5, 1),)),),
        final_op_ids=("s",), metadata={"predicted_difficulty": "medium", "suspected_failures": ["candidate_miss"]},
    )
    await store.save_trace(t)
    assert await store.list_services()
    rows = await store.list_traces(TraceQuery(service_id="pg_svc"))
    assert rows
    assert await store.get_trace("pg_t1")

    lineage = await store.get_query_lineage("pg_fq")
    assert lineage["origin"]["source"] == "forge"

    await store.close()


@requires_postgres
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


class _Connection:
    def __init__(self):
        self.executed = []
        self.fetch_call = None

    async def execute(self, sql, *params):
        self.executed.append((sql, params))

    async def fetch(self, sql, *params):
        self.fetch_call = (sql, params)
        return []


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_postgres_query_scope_and_index_sql_without_live_server():
    connection = _Connection()
    store = PostgresStore("postgresql://unused")
    store._pool = _Pool(connection)

    await store.init_db()
    await store.list_traces(TraceQuery(run_id="run-a", query_id="q-1"))

    assert any("idx_traces_run_query" in sql for sql, _ in connection.executed)
    sql, params = connection.fetch_call
    assert "run_id = $1" in sql
    assert "query_id = $2" in sql
    assert params[:2] == ("run-a", "q-1")
