"""Schema v3 is additive: v2 files are accepted, migrated in place with a backup, never reset."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from retrieval_observatory.store import migrate
from retrieval_observatory.store.base import InvestigationFilter, InvestigationScope
from retrieval_observatory.store.migrate import IncompatibleSchemaError, ensure_supported_schema, migrate_database
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

V3_TABLES = ["investigation_pairs", "investigation_projections", "investigation_summaries"]
RUN = "run-v2"


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _version(db_path: Path) -> int:
    with sqlite3.connect(db_path) as db:
        return int(db.execute("PRAGMA user_version").fetchone()[0])


def _rows(db_path: Path, table: str) -> list[tuple]:
    with sqlite3.connect(db_path) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


async def _v2_database(db_path: Path) -> None:
    """A populated v2 file: today's schema minus the v3 tables, stamped user_version = 2."""
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run(RUN, "exp", "{}")
    await store.save_traces([
        RetrievalTrace(
            trace_id="t1", service_id="bench", run_id=RUN, query_id="q1", query_text="hello", pipeline_id="bm25",
            spans=(OperatorSpan.source("source", "Source", (Candidate("d1", 1.0, 1),)),), final_op_ids=("source",),
        )
    ])
    await store.save_qrels(RUN, {"q1": {"d1": 1}})
    await store.save_metric(RUN, "bm25", "q1", 0, "recall", 10, 1.0)
    with sqlite3.connect(db_path) as db:
        for table in V3_TABLES:
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version = 2")
        db.commit()
    assert _version(db_path) == 2 and not (_tables(db_path) & set(V3_TABLES))


@pytest.fixture
async def v2_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "legacy.db"
    await _v2_database(db_path)
    return db_path


def _snapshot(db_path: Path) -> dict[str, list[tuple]]:
    return {table: _rows(db_path, table) for table in ("runs", "traces", "run_qrels", "metric_scores")}


async def test_migrate_database_adds_only_the_three_tables_with_a_backup(v2_db: Path) -> None:
    ensure_supported_schema(v2_db)
    before_tables = _tables(v2_db)
    before_rows = _snapshot(v2_db)

    report = migrate_database(v2_db)

    assert report["status"] == "migrated"
    assert (report["from_version"], report["to_version"]) == (2, 3)
    assert report["tables_added"] == V3_TABLES
    assert _tables(v2_db) == before_tables | set(V3_TABLES)
    assert _version(v2_db) == 3
    assert _snapshot(v2_db) == before_rows
    assert before_rows["traces"], "fixture must hold a trace to compare"

    backup = Path(report["backup_path"])
    assert backup.exists() and backup.name.startswith("legacy.db.bak-v2-")
    assert _version(backup) == 2 and not (_tables(backup) & set(V3_TABLES))
    assert _snapshot(backup) == before_rows
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    ensure_supported_schema(v2_db)

    again = migrate_database(v2_db)
    assert again["status"] == "already_current" and again["backup_path"] is None
    assert [path.name for path in v2_db.parent.glob("*.bak-*")] == [backup.name]


async def test_failed_ddl_rolls_back_and_keeps_the_original_intact(v2_db: Path, monkeypatch) -> None:
    before_rows = _snapshot(v2_db)
    monkeypatch.setattr(migrate, "_INVESTIGATION_DDL", (*migrate._INVESTIGATION_DDL[:1], "CREATE TABLE"))

    with pytest.raises(sqlite3.OperationalError):
        migrate_database(v2_db)

    assert _version(v2_db) == 2
    assert not (_tables(v2_db) & set(V3_TABLES))
    assert _snapshot(v2_db) == before_rows
    assert len(list(v2_db.parent.glob("legacy.db.bak-v2-*"))) == 1


async def test_migrate_without_backup_writes_no_copy(v2_db: Path) -> None:
    report = migrate_database(v2_db, backup=False)
    assert report["status"] == "migrated" and report["backup_path"] is None
    assert not list(v2_db.parent.glob("*.bak-*"))


def test_unsupported_legacy_schema_is_rejected_never_reset(tmp_path: Path) -> None:
    db_path = tmp_path / "beta.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE trace_stages (trace_id TEXT, stage INTEGER)")
        db.execute("INSERT INTO trace_stages VALUES ('t', 0)")
        db.execute("PRAGMA user_version = 1")
        db.commit()
    with pytest.raises(IncompatibleSchemaError):
        ensure_supported_schema(db_path)
    with pytest.raises(IncompatibleSchemaError):
        migrate_database(db_path)
    assert _version(db_path) == 1
    assert _rows(db_path, "trace_stages") == [("t", 0)]
    assert not list(tmp_path.glob("*.bak-*"))


async def test_writable_init_db_migrates_a_v2_file_in_place(v2_db: Path) -> None:
    before_rows = _snapshot(v2_db)
    await SQLiteStore(str(v2_db)).init_db()
    assert _version(v2_db) == 3
    assert set(V3_TABLES) <= _tables(v2_db)
    assert _snapshot(v2_db) == before_rows


async def test_read_only_v2_file_stays_readable_with_empty_investigation_reads(v2_db: Path) -> None:
    snapshot = v2_db.read_bytes()
    reader = SQLiteStore(str(v2_db), read_only=True)
    await reader.init_db()
    scope = InvestigationScope(run_id=RUN, pipeline_id="bm25", evaluation_digest="eval")

    assert reader.investigation_tables_available is False
    assert [run["run_id"] for run in await reader.list_runs()] == [RUN]
    assert [trace.trace_id for trace in await reader.get_traces(RUN)] == ["t1"]
    assert await reader.get_investigation_projection(scope) is None
    assert await reader.list_investigation_projections(RUN) == []
    page = await reader.list_investigation_pairs(scope, InvestigationFilter(outcome="loss"))
    assert (page.rows, page.total, page.next_cursor) == ([], 0, None)
    assert await reader.get_investigation_pair(scope, trace_id="t1", namespace="docs", unit="document", entity_id="d1") is None
    assert (await reader.list_investigation_summaries(scope, "query")).total == 0
    assert await reader.get_investigation_summary(scope, "run", "run") is None
    with pytest.raises(RuntimeError, match="migrate_database"):
        await reader.replace_investigation_projection(
            scope, rows=[], summaries=[], derivation_version="d1", judgment_digest="j1", trace_count=0
        )
    with pytest.raises(RuntimeError, match="migrate_database"):
        await reader.delete_investigation_projection(scope)

    assert v2_db.read_bytes() == snapshot
    assert _version(v2_db) == 2 and not (_tables(v2_db) & set(V3_TABLES))

    migrate_database(v2_db, backup=False)
    assert (await SQLiteStore(str(v2_db), read_only=True).list_investigation_pairs(scope)).total == 0
    fresh = SQLiteStore(str(v2_db), read_only=True)
    await fresh.init_db()
    assert fresh.investigation_tables_available is True
