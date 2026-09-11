#!/usr/bin/env python3
"""Bake the hosted-demo databases: copy, migrate schema, mark read-only.

The container opens every database with SQLite `mode=ro`, so the schema must be complete
before the image is built. Run this once locally before `docker build -f deploy/Dockerfile`.

    python deploy/prepare_data.py                      # BEIR sweep DBs from .retobs/
    python deploy/prepare_data.py name=path [...]      # explicit sources
"""
from __future__ import annotations

import asyncio
import shutil
import stat
import sys
from pathlib import Path

from retrieval_observatory.store.sqlite import SQLiteStore

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCES = {
    "nfcorpus": ".retobs/publish_sweep_nfcorpus.db",
    "scifact": ".retobs/publish_sweep_scifact.db",
    "fiqa": ".retobs/publish_sweep_fiqa.db",
}


async def bake(name: str, source: Path) -> Path:
    target = HERE / "data" / f"{name}.db"
    if not source.exists():
        raise SystemExit(f"missing source database: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.copyfile(source, target)
    await SQLiteStore(db_path=str(target)).init_db()  # writable once: migrates the schema
    await SQLiteStore(db_path=str(target), read_only=True).init_db()  # proves it opens mode=ro
    target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    print(f"{name}: {source} -> {target} ({target.stat().st_size / 1e6:.1f} MB, read-only)")
    return target


async def main(argv: list[str]) -> None:
    sources = dict(arg.split("=", 1) for arg in argv) if argv else DEFAULT_SOURCES
    for name, source in sources.items():
        await bake(name, Path(source))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
