from __future__ import annotations

import json
from pathlib import Path

import pytest

from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore


@pytest.mark.asyncio
async def test_registry_slug_and_collision(tmp_path: Path) -> None:
    db_a = tmp_path / "results.db"
    db_b = tmp_path / "other" / "results.db"
    db_b.parent.mkdir(parents=True)
    for p in (db_a, db_b):
        store = SQLiteStore(db_path=str(p))
        await store.init_db()
        await store.save_run("run1", "exp", "{}")
        await store.finish_run("run1")

    registry = DbRegistry([str(db_a), str(db_b)])
    ids = registry.list_db_ids()
    assert len(ids) == 2
    assert ids[0] == "results"
    assert ids[1] == "results_2"

    sources = await registry.list_sources()
    assert sources[0]["run_count"] == 1
    assert sources[1]["run_count"] == 1


@pytest.mark.asyncio
async def test_registry_list_runs_includes_db_id(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run("abc12345", "nfcorpus-sweep", json.dumps({"dataset": {"name": "beir/nfcorpus"}}))
    await store.finish_run("abc12345")

    registry = DbRegistry([str(db_path)])
    runs = await registry.list_runs("demo")
    assert len(runs) == 1
    assert runs[0]["db_id"] == "demo"
    assert runs[0]["run_id"] == "abc12345"
