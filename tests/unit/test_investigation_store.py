"""Investigation projection store: transactional rebuilds, indexed keyset pagination, scoping.

Runs against SQLite always and against PostgreSQL when RETOBS_POSTGRES_DSN is set.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import fields
from pathlib import Path
from uuid import uuid4

import aiosqlite
import pytest

from retrieval_observatory.store.base import (
    INVESTIGATION_SORT_KEYS,
    InvestigationFilter,
    InvestigationScope,
)
from retrieval_observatory.store.postgres import PostgresStore
from retrieval_observatory.store.sqlite import SQLiteStore

requires_postgres = pytest.mark.skipif(
    not os.getenv("RETOBS_POSTGRES_DSN"),
    reason="RETOBS_POSTGRES_DSN not set — skipping Postgres tests",
)


def _scope(**overrides) -> InvestigationScope:
    base = {"run_id": f"run-{uuid4().hex[:8]}", "pipeline_id": "bm25", "evaluation_digest": "eval-a"}
    return InvestigationScope(**{**base, **overrides})


def _row(scope: InvestigationScope, query_id: str, entity_id: str, **overrides) -> dict:
    row = {
        "schema_version": 1, "derivation_version": "d1",
        "run_id": scope.run_id, "pipeline_id": scope.pipeline_id,
        "trace_id": f"t-{query_id}", "query_id": query_id,
        "namespace": "docs", "entity_id": entity_id, "unit": "document", "entity_revision": None,
        "judgment": "relevant", "grade": 1, "final_membership": "absent", "in_final_output": False,
        "final_rank": None, "outcome": "loss", "confusion": "fn", "capture_state": "observed",
        "observed": True, "loss_boundary": "rerank", "priority": 1,
        "events": [{"op_id": "bm25", "action": "dropped"}], "occurrence_entity_ids": [entity_id],
        "evaluation_digest": scope.evaluation_digest, "judgment_digest": "j1", "trace_digest": "tr1",
        "investigation_link": f"/investigate/{query_id}/{entity_id}",
    }
    row.update(overrides)
    return row


def _sort_key(row: dict, order: str) -> tuple:
    return tuple(row[column] for column in INVESTIGATION_SORT_KEYS[order])


def _mixed_rows(scope: InvestigationScope) -> list[dict]:
    """Rows that spread every filterable column across at least two values."""
    return [
        _row(scope, "q1", "d1", priority=3),
        _row(scope, "q1", "d2", priority=1, outcome="hit", confusion="tp", final_membership="present",
             in_final_output=True, final_rank=1, loss_boundary=None),
        _row(scope, "q2", "d1", priority=2, judgment="irrelevant", grade=0, capture_state="inferred", observed=False,
             loss_boundary="fusion"),
        _row(scope, "q2", "c1", priority=1, unit="chunk", namespace="chunks", entity_revision="r2"),
        _row(scope, "q3", "d3", priority=1, trace_id="t-q3-b", outcome="unknown", capture_state="uncaptured"),
    ]


async def _replace(store, scope: InvestigationScope, rows: list[dict], summaries=()) -> None:
    await store.replace_investigation_projection(
        scope, rows=rows, summaries=list(summaries), derivation_version="d1", judgment_digest="j1",
        trace_count=len({row["trace_id"] for row in rows}),
    )


async def _walk(store, scope: InvestigationScope, *, limit: int, order: str = "priority", filters=None) -> list[dict]:
    collected: list[dict] = []
    cursor = None
    while True:
        page = await store.list_investigation_pairs(scope, filters, limit=limit, cursor=cursor, order=order)
        collected.extend(page.rows)
        if page.next_cursor is None:
            return collected
        cursor = page.next_cursor


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
async def store(request, tmp_path: Path):
    if request.param == "sqlite":
        store = SQLiteStore(str(tmp_path / "investigation.db"))
        await store.init_db()
        yield store
        return
    store = PostgresStore(dsn=os.environ["RETOBS_POSTGRES_DSN"])
    await store.init_db()
    yield store
    await store.close()


async def test_replace_then_list_returns_payloads_in_priority_order(store) -> None:
    scope = _scope()
    rows = _mixed_rows(scope)
    await _replace(store, scope, rows)

    page = await store.list_investigation_pairs(scope, limit=200)
    assert page.total == len(rows)
    assert page.next_cursor is None
    assert page.rows == sorted(rows, key=lambda row: _sort_key(row, "priority"))
    projection = await store.get_investigation_projection(scope)
    assert projection["status"] == "complete"
    assert projection["row_count"] == len(rows)
    assert projection["trace_count"] == 3
    assert projection["finished_at"] is not None
    assert [p["evaluation_digest"] for p in await store.list_investigation_projections(scope.run_id)] == ["eval-a"]


async def test_cursor_pagination_walks_every_row_exactly_once(store) -> None:
    scope = _scope()
    rows = [_row(scope, f"q{i:03d}", f"d{i % 7}", priority=i % 5) for i in range(205)]
    await _replace(store, scope, rows)
    expected = sorted(rows, key=lambda row: _sort_key(row, "priority"))

    assert await _walk(store, scope, limit=2) == expected
    assert await _walk(store, scope, limit=200) == expected

    clamped_up = await store.list_investigation_pairs(scope, limit=500)
    assert len(clamped_up.rows) == 200 and clamped_up.next_cursor is not None and clamped_up.total == 205
    clamped_down = await store.list_investigation_pairs(scope, limit=0)
    assert len(clamped_down.rows) == 1 and clamped_down.next_cursor is not None
    assert await _walk(store, scope, limit=2, order="entity") == sorted(rows, key=lambda row: _sort_key(row, "entity"))
    with pytest.raises(ValueError):
        await store.list_investigation_pairs(scope, cursor="not-a-cursor")


@pytest.mark.parametrize("field", [f.name for f in fields(InvestigationFilter)])
async def test_each_filter_field_narrows_rows_and_total_consistently(store, field: str) -> None:
    scope = _scope()
    rows = _mixed_rows(scope)
    await _replace(store, scope, rows)
    values = {row[field] for row in rows if row[field] is not None}
    assert len(values) >= 2, f"fixture must spread {field}"
    for value in values:
        expected = sorted((row for row in rows if row[field] == value), key=lambda row: _sort_key(row, "priority"))
        page = await store.list_investigation_pairs(scope, InvestigationFilter(**{field: value}), limit=200)
        assert page.rows == expected
        assert page.total == len(expected)
        assert await _walk(store, scope, limit=1, filters=InvestigationFilter(**{field: value})) == expected


async def test_entity_order_keeps_one_entity_together_across_queries(store) -> None:
    scope = _scope()
    rows = [_row(scope, "q1", "d1", priority=2), _row(scope, "q2", "d2", priority=1), _row(scope, "q3", "d1", priority=1)]
    await _replace(store, scope, rows)
    page = await store.list_investigation_pairs(scope, order="entity")
    assert [(row["entity_id"], row["query_id"]) for row in page.rows] == [("d1", "q3"), ("d1", "q1"), ("d2", "q2")]


async def test_scopes_never_leak_across_pipeline_run_or_digest(store) -> None:
    shared = _scope()
    other_pipeline = _scope(run_id=shared.run_id, pipeline_id="hybrid")
    other_run = _scope(pipeline_id=shared.pipeline_id)
    other_digest = _scope(run_id=shared.run_id, pipeline_id=shared.pipeline_id, evaluation_digest="eval-b")
    for scope, priority in ((shared, 1), (other_pipeline, 2), (other_run, 3), (other_digest, 4)):
        await _replace(store, scope, [_row(scope, "q1", "d1", priority=priority)])

    for scope, priority in ((shared, 1), (other_pipeline, 2), (other_run, 3), (other_digest, 4)):
        page = await store.list_investigation_pairs(scope)
        assert page.total == 1 and page.rows[0]["priority"] == priority
        assert (await store.get_investigation_pair(
            scope, trace_id="t-q1", namespace="docs", unit="document", entity_id="d1"
        ))["priority"] == priority
    assert {p["pipeline_id"] for p in await store.list_investigation_projections(shared.run_id)} == {"bm25", "hybrid"}

    await store.delete_investigation_projection(shared)
    assert (await store.list_investigation_pairs(shared)).total == 0
    assert await store.get_investigation_projection(shared) is None
    assert (await store.list_investigation_pairs(other_digest)).total == 1


async def test_replace_is_idempotent_drops_stale_rows_and_accepts_empty(store) -> None:
    scope = _scope()
    rows = _mixed_rows(scope)
    await _replace(store, scope, rows)
    await _replace(store, scope, rows)
    assert (await store.list_investigation_pairs(scope)).total == len(rows)

    await _replace(store, scope, rows[:2])
    page = await store.list_investigation_pairs(scope, limit=200)
    assert page.total == 2
    assert page.rows == sorted(rows[:2], key=lambda row: _sort_key(row, "priority"))
    assert await store.get_investigation_pair(scope, trace_id="t-q3-b", namespace="docs", unit="document", entity_id="d3") is None

    await _replace(store, scope, [])
    empty = await store.list_investigation_pairs(scope)
    assert (empty.rows, empty.total, empty.next_cursor) == ([], 0, None)
    projection = await store.get_investigation_projection(scope)
    assert (projection["status"], projection["row_count"]) == ("complete", 0)


async def test_interrupted_rebuild_leaves_old_projection_complete(tmp_path: Path, monkeypatch) -> None:
    store = SQLiteStore(str(tmp_path / "interrupted.db"))
    await store.init_db()
    scope = _scope()
    old_rows = _mixed_rows(scope)
    await _replace(store, scope, old_rows, summaries=[{"kind": "run", "key": "run", "payload": {"n": 5}}])
    before = await store.get_investigation_projection(scope)

    original = aiosqlite.Connection.executemany

    async def failing_insert(self, sql, parameters):
        if "INSERT INTO investigation_pairs" in sql:
            raise RuntimeError("disk full mid-rebuild")
        return await original(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "executemany", failing_insert)
    with pytest.raises(RuntimeError, match="mid-rebuild"):
        await _replace(store, scope, [_row(scope, "new", "n1")])
    monkeypatch.undo()

    page = await store.list_investigation_pairs(scope, limit=200)
    assert page.rows == sorted(old_rows, key=lambda row: _sort_key(row, "priority"))
    assert await store.get_investigation_projection(scope) == before
    assert (await store.get_investigation_summary(scope, "run", "run"))["payload"] == {"n": 5}


async def test_non_ascii_ids_round_trip(store) -> None:
    scope = _scope()
    rows = [_row(scope, "问题-1", "документ/чанк-1"), _row(scope, "问题-1", "ascii", priority=0)]
    await _replace(store, scope, rows)
    assert await _walk(store, scope, limit=1) == sorted(rows, key=lambda row: _sort_key(row, "priority"))
    found = await store.get_investigation_pair(scope, trace_id="t-问题-1", namespace="docs", unit="document", entity_id="документ/чанк-1")
    assert found == rows[0]
    assert (await store.list_investigation_pairs(scope, InvestigationFilter(query_id="问题-1"))).total == 2


async def test_summaries_replace_list_get_with_isolated_kinds(store) -> None:
    scope = _scope()
    summaries = [
        {"kind": "query", "key": "q2", "payload": {"losses": 1}},
        {"kind": "query", "key": "q1", "payload": {"losses": 2}},
        {"kind": "query", "key": "q3", "payload": {"losses": 0}},
        {"kind": "document", "key": "d1", "payload": {"queries": ["q1", "q2"]}},
        {"kind": "run", "key": "run", "payload": {"rows": 3}},
    ]
    await _replace(store, scope, _mixed_rows(scope), summaries=summaries)

    first = await store.list_investigation_summaries(scope, "query", limit=2)
    assert [row["key"] for row in first.rows] == ["q1", "q2"] and first.total == 3
    rest = await store.list_investigation_summaries(scope, "query", limit=2, cursor=first.next_cursor)
    assert rest.rows == [{"key": "q3", "payload": {"losses": 0}}] and rest.next_cursor is None
    assert (await store.list_investigation_summaries(scope, "document")).rows == [
        {"key": "d1", "payload": {"queries": ["q1", "q2"]}}
    ]
    assert await store.get_investigation_summary(scope, "run", "run") == {"key": "run", "payload": {"rows": 3}}
    assert await store.get_investigation_summary(scope, "query", "run") is None
    assert (await store.list_investigation_summaries(scope, "stage")).total == 0

    await _replace(store, scope, [], summaries=[{"kind": "run", "key": "run", "payload": {"rows": 0}}])
    assert (await store.list_investigation_summaries(scope, "query")).total == 0
    assert (await store.get_investigation_summary(scope, "run", "run"))["payload"] == {"rows": 0}


async def test_read_only_store_reads_after_writable_init_but_cannot_replace(tmp_path: Path) -> None:
    db_path = tmp_path / "ro.db"
    scope = _scope()
    writable = SQLiteStore(str(db_path))
    await writable.init_db()
    rows = _mixed_rows(scope)
    await _replace(writable, scope, rows, summaries=[{"kind": "run", "key": "run", "payload": {"n": 1}}])

    reader = SQLiteStore(str(db_path), read_only=True)
    await reader.init_db()
    assert (await reader.list_investigation_pairs(scope, limit=200)).rows == sorted(
        rows, key=lambda row: _sort_key(row, "priority")
    )
    assert (await reader.get_investigation_projection(scope))["status"] == "complete"
    assert (await reader.get_investigation_summary(scope, "run", "run"))["payload"] == {"n": 1}
    with pytest.raises(sqlite3.OperationalError):
        await _replace(reader, scope, rows)
    with pytest.raises(sqlite3.OperationalError):
        await reader.delete_investigation_projection(scope)
    assert (await reader.list_investigation_pairs(scope)).total == len(rows)


async def test_read_methods_never_touch_the_file(tmp_path: Path) -> None:
    db_path = tmp_path / "pure.db"
    scope = _scope()
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await _replace(store, scope, _mixed_rows(scope), summaries=[{"kind": "query", "key": "q1", "payload": {}}])
    snapshot = db_path.read_bytes()

    for reader in (store, SQLiteStore(str(db_path)), SQLiteStore(str(db_path), read_only=True)):
        await reader.get_investigation_projection(scope)
        await reader.list_investigation_projections(scope.run_id)
        first = await reader.list_investigation_pairs(scope, InvestigationFilter(outcome="loss"), limit=1)
        await reader.list_investigation_pairs(scope, limit=1, cursor=first.next_cursor, order="entity")
        await reader.get_investigation_pair(scope, trace_id="t-q1", namespace="docs", unit="document", entity_id="d1")
        await reader.list_investigation_summaries(scope, "query")
        await reader.get_investigation_summary(scope, "query", "q1")
    assert db_path.read_bytes() == snapshot
