"""Clean-beta schema detection, reset, and additive migration helpers.

retobs deliberately does not dual-read obsolete trace schemas. Existing beta
databases must be reset explicitly before the unified trace store is opened.

Schema history (``PRAGMA user_version``):

* 2 — unified trace store.
* 3 — adds the investigation projection tables (``investigation_pairs``,
  ``investigation_summaries``, ``investigation_projections``). Purely additive:
  no existing table, index, or row is touched, so v2 files migrate in place.
  Later v3 releases add indexes only (``_INVESTIGATION_ORDER_INDEX_DDL``); migrating a
  file already at v3 creates any that are missing, with no version bump.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from retrieval_observatory.store.sqlite import _INVESTIGATION_DDL, _INVESTIGATION_ORDER_INDEX_DDL, _created_table_names


SCHEMA_VERSION = 3
_SUPPORTED_VERSIONS = (0, 2, SCHEMA_VERSION)
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
    if legacy or (version not in _SUPPORTED_VERSIONS):
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


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _index_names(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def migrate_database(db_path: Path, *, backup: bool = True) -> dict:
    """Bring a supported v0/v2 file to v3 in place, additively and transactionally.

    The v2 -> v3 delta only creates tables and indexes, so no row is dropped or rewritten
    and a package rollback never needs a database downgrade: an older retobs opens the
    file as before and simply never reads the extra tables.

    With ``backup`` a consistent copy is taken with SQLite's online backup API BEFORE
    anything changes, at ``<db>.bak-v<old_version>-<UTC timestamp>``. Verify it with
    ``sqlite3 <bak> 'PRAGMA integrity_check'`` (expects ``ok``). The DDL and the version
    stamp run inside ``BEGIN IMMEDIATE``; any failure rolls back and leaves the original
    file exactly as it was. An already-current file returns ``already_current`` without
    taking a backup.
    """
    ensure_supported_schema(db_path)
    with sqlite3.connect(db_path) as db:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        before = _table_names(db)
        indexes_before = _index_names(db)
    if version == SCHEMA_VERSION:
        # Additive index DDL only (`IF NOT EXISTS`), so no backup; a reset file has no pairs table.
        if "investigation_pairs" in before:
            with sqlite3.connect(db_path) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _INVESTIGATION_ORDER_INDEX_DDL:
                        db.execute(statement)
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                indexes_after = _index_names(db)
        else:
            indexes_after = indexes_before
        return {
            "status": "already_current", "from_version": version, "to_version": SCHEMA_VERSION,
            "backup_path": None, "tables_added": [], "indexes_added": sorted(indexes_after - indexes_before),
        }
    backup_path = None
    if backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = db_path.with_name(f"{db_path.name}.bak-v{version}-{stamp}")
        with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
    with sqlite3.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            for statement in _INVESTIGATION_DDL:
                db.execute(statement)
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
        except Exception:
            db.rollback()
            raise
        after = _table_names(db)
        indexes_after = _index_names(db)
    return {
        "status": "migrated", "from_version": version, "to_version": SCHEMA_VERSION,
        "backup_path": str(backup_path) if backup_path else None,
        "tables_added": sorted(after - before), "indexes_added": sorted(indexes_after - indexes_before),
    }
