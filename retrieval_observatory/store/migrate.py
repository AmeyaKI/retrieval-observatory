"""Clean-beta schema detection and reset helpers.

retobs deliberately does not dual-read obsolete trace schemas. Existing beta
databases must be reset explicitly before the unified trace store is opened.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

from retrieval_observatory.store.sqlite import _created_table_names


SCHEMA_VERSION = 2
_LEGACY_RESULTS_TABLE = "raw" + "_results"
_LEGACY_SPLIT_TRACE_TABLE = "traces" + "_v2"
_LEGACY_TABLES = frozenset({_LEGACY_RESULTS_TABLE, _LEGACY_SPLIT_TRACE_TABLE, "trace_stages"})

# Every table the current store creates (derived from its DDL, so a new table can never be
# left behind by `retobs storage reset`) plus the obsolete beta tables reset must clear.
_RETOBS_TABLES = frozenset(_created_table_names()) | _LEGACY_TABLES


class IncompatibleSchemaError(RuntimeError):
    """Raised when a beta database uses an obsolete trace schema."""


def ensure_supported_schema(db_path: Path) -> None:
    """Reject old V1/V2 databases instead of silently lifting their contents."""
    if not db_path.exists():
        return
    with sqlite3.connect(db_path) as db:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(traces)")
        } if "traces" in tables else set()
    legacy = _LEGACY_SPLIT_TRACE_TABLE in tables or "trace_stages" in tables or (
        "traces" in tables and not {"service_id", "run_id", "topology_hash", "trace_json"} <= columns
    )
    if legacy or (version not in (0, SCHEMA_VERSION)):
        raise IncompatibleSchemaError(
            "Incompatible beta trace schema; run `retobs storage reset` before continuing."
        )


def reset_database(db_path: Path) -> None:
    """Drop known retobs tables transactionally and mark the clean schema version."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        for table in sorted(_RETOBS_TABLES):
            db.execute(f'DROP TABLE IF EXISTS "{table}"')
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
