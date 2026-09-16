"""`retobs storage reset` must drop every table the current store creates."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from retrieval_observatory.store import migrate
from retrieval_observatory.store.sqlite import SQLiteStore, _created_table_names


def test_reset_table_set_is_derived_from_store_ddl() -> None:
    assert set(_created_table_names()) <= set(migrate._RETOBS_TABLES)
    assert {"diagnostic_findings", "analysis_records"} <= set(migrate._RETOBS_TABLES)
    # Obsolete beta tables are still cleared.
    assert {"trace_stages", "traces_v2", "raw_results"} <= set(migrate._RETOBS_TABLES)


@pytest.mark.asyncio
async def test_reset_database_leaves_no_retobs_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "reset.db"
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_analysis_record("cohort", "c1", {"queries": ["q1"]})
    with sqlite3.connect(db_path) as db:
        before = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"diagnostic_findings", "analysis_records"} <= before

    migrate.reset_database(db_path)

    with sqlite3.connect(db_path) as db:
        after = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
    leftovers = after & set(_created_table_names())
    assert not leftovers, f"reset left retobs tables behind: {sorted(leftovers)}"
    assert version == migrate.SCHEMA_VERSION
