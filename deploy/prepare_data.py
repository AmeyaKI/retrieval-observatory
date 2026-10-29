#!/usr/bin/env python3
"""Bake the hosted-demo databases into deploy/data/<name>.db.gz.

The container opens every database with SQLite `mode=ro`, so each one must be complete before
the image is built. For every ``name=path`` source this script:

1. copies it and migrates it to the current schema (the only writable step);
2. rewrites absolute paths under each ``--relative-to`` directory to relative ones, so the public
   site never shows where the data was built;
3. indexes every run for Investigate (``retobs storage index``), so the read-only site never has
   to compute investigation rows on request;
4. refuses to finish if any absolute path or e-mail address is left anywhere in the database;
5. proves it opens read-only and writes it gzip-compressed (the Dockerfile unpacks it).

    python deploy/prepare_data.py scifact=DIR/scifact.db demo=DIR/demo/demo.db \\
        integration=DIR/project/.retobs/results.db --relative-to DIR/project --relative-to DIR

See deploy/README.md for how DIR is produced.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from retrieval_observatory.store.sqlite import SQLiteStore

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
# Absolute paths on common hosts, and e-mail addresses: neither belongs on a public demo.
LEAKS = (
    re.compile(r"(?<![\w.])/(?:Users|home|private|tmp|var|opt|root|srv|mnt|Volumes)/[^\"' ,\]\)]*"),
    re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.IGNORECASE),
)


def _text_columns(con: sqlite3.Connection) -> list[tuple[str, str]]:
    columns = []
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        for _cid, column, kind, *_rest in con.execute(f'PRAGMA table_info("{table}")'):
            if kind.upper() in ("TEXT", "") or "CHAR" in kind.upper() or "JSON" in kind.upper():
                columns.append((table, column))
    return columns


def relativize(db: Path, roots: list[Path]) -> int:
    """Rewrite ``<root>/x`` to ``x`` and ``<root>`` to ``.`` in every text column; returns paths rewritten."""
    # Both spellings of each root (macOS resolves /tmp to /private/tmp), longest first so a
    # nested root is rewritten before its parent.
    prefixes = sorted({str(form) for root in roots for form in (root.absolute(), root.resolve())}, key=len, reverse=True)
    changed = 0
    with sqlite3.connect(db) as con:
        for table, column in _text_columns(con):
            for prefix in prefixes:
                for old, new in ((prefix + "/", ""), (prefix, ".")):
                    (count,) = con.execute(
                        f'SELECT COALESCE(SUM((length("{column}") - length(replace("{column}", ?, ""))) / length(?)), 0) '
                        f'FROM "{table}" WHERE instr("{column}", ?) > 0',
                        (old, old, old),
                    ).fetchone()
                    if count:
                        con.execute(f'UPDATE "{table}" SET "{column}" = replace("{column}", ?, ?) WHERE instr("{column}", ?) > 0', (old, new, old))
                        changed += count
    return changed


def index_runs(db: Path) -> list[str]:
    """Index every (run, pipeline) that has traces, through the public CLI."""
    with sqlite3.connect(db) as con:
        scopes = con.execute("SELECT DISTINCT run_id, pipeline_id FROM traces WHERE run_id IS NOT NULL ORDER BY run_id, pipeline_id").fetchall()
    for run_id, pipeline_id in scopes:
        subprocess.run(
            [sys.executable, "-m", "retrieval_observatory.cli", "storage", "index", run_id, "--db", str(db), "--pipeline", pipeline_id],
            check=True, capture_output=True, text=True,
        )
    return [f"{run_id}/{pipeline_id}" for run_id, pipeline_id in scopes]


def leaks(db: Path) -> list[str]:
    found = []
    with sqlite3.connect(db) as con:
        for table, column in _text_columns(con):
            for (value,) in con.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
                text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
                for pattern in LEAKS:
                    found.extend(f"{table}.{column}: {match.group(0)[:80]}" for match in pattern.finditer(text))
    return found


async def bake(name: str, source: Path, roots: list[Path], workdir: Path) -> Path:
    if not source.is_file():
        raise SystemExit(f"missing source database: {source}")
    db = workdir / f"{name}.db"
    shutil.copyfile(source, db)
    await SQLiteStore(db_path=str(db)).init_db()  # writable once: migrates the schema
    changed = relativize(db, roots)
    indexed = index_runs(db)
    found = leaks(db)
    if found:
        raise SystemExit(f"{name}: refusing to bake, {len(found)} absolute path(s) or e-mail(s) left:\n  " + "\n  ".join(found[:20]))
    with sqlite3.connect(db) as con:
        con.execute("VACUUM")
    await SQLiteStore(db_path=str(db), read_only=True).init_db()  # proves it opens mode=ro
    target = DATA / f"{name}.db.gz"
    DATA.mkdir(parents=True, exist_ok=True)
    # mtime=0 and a fixed inner name: no build-host time or path in the archive header.
    with db.open("rb") as raw, target.open("wb") as out, gzip.GzipFile(filename=f"{name}.db", mode="wb", fileobj=out, compresslevel=9, mtime=0) as packed:
        shutil.copyfileobj(raw, packed)
    print(
        f"{name}: {db.stat().st_size / 1e6:.1f} MB -> {target.relative_to(HERE.parent)} ({target.stat().st_size / 1e6:.1f} MB); "
        f"{changed} path(s) made relative; indexed {', '.join(indexed) or 'no runs'}"
    )
    return target


async def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Bake hosted-demo databases into deploy/data/<name>.db.gz.")
    parser.add_argument("sources", nargs="+", metavar="name=path")
    parser.add_argument("--relative-to", action="append", default=[], type=Path, metavar="DIR",
                        help="Rewrite absolute paths under DIR to relative ones (repeatable).")
    args = parser.parse_args(argv)
    sources = [item.split("=", 1) for item in args.sources]
    if any(len(pair) != 2 or not pair[0].isidentifier() for pair in sources):
        raise SystemExit("each source is name=path, with name a plain identifier")
    with tempfile.TemporaryDirectory() as workdir:
        for name, source in sources:
            await bake(name, Path(source), args.relative_to, Path(workdir))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
