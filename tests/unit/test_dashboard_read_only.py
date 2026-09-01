from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore


async def _seed_run(db_path: Path, run_id: str) -> None:
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(run_id, f"exp-{run_id}", json.dumps({"dataset": {"name": "beir/nfcorpus"}}))
    manifest = {
        "schema_version": 3,
        "dataset": {
            "name": "beir/nfcorpus",
            "query_hash": "queries:nfcorpus",
            "corpus_hash": "corpus:nfcorpus",
            "qrel_hash": "qrels:nfcorpus",
        },
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "execution": {"seed": 1, "cache_results": False, "timeout_ms": 5000},
        "git_commit": "commit",
        "git_dirty": False,
        "models": [{"model": "bm25"}],
        "packages": {"retobs": "test"},
    }
    await store.save_run_manifest(run_id, manifest)
    await store.finish_run(run_id)


@pytest.fixture
async def demo_registry(tmp_path: Path) -> DbRegistry:
    db_path = tmp_path / "demo.db"
    await _seed_run(db_path, "aaaaaaaa")
    return DbRegistry([str(db_path)])


def _client(registry: DbRegistry, monkeypatch, read_only: str | None) -> TestClient:
    if read_only is None:
        monkeypatch.delenv("RETOBS_READ_ONLY", raising=False)
    else:
        monkeypatch.setenv("RETOBS_READ_ONLY", read_only)
    app = create_app(registry=registry, enable_uploads=True)
    return TestClient(app)


@pytest.mark.asyncio
async def test_read_only_allows_get_dbs(demo_registry: DbRegistry, monkeypatch) -> None:
    client = _client(demo_registry, monkeypatch, "1")
    response = client.get("/dbs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_read_only_allows_compare_post(demo_registry: DbRegistry, monkeypatch) -> None:
    client = _client(demo_registry, monkeypatch, "1")
    response = client.post("/compare", json={"selections": []})
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_read_only_blocks_trigger_run(demo_registry: DbRegistry, monkeypatch) -> None:
    client = _client(demo_registry, monkeypatch, "1")
    db_id = client.get("/dbs").json()[0]["db_id"]
    response = client.post(f"/dbs/{db_id}/runs", json={"config": {"name": "x"}})
    assert response.status_code == 403
    assert response.json()["detail"] == "Hosted demo is read-only"


@pytest.mark.asyncio
async def test_read_only_off_does_not_403_runs_for_readonly_reason(demo_registry: DbRegistry, monkeypatch) -> None:
    client = _client(demo_registry, monkeypatch, None)
    db_id = client.get("/dbs").json()[0]["db_id"]
    response = client.post(f"/dbs/{db_id}/runs", json={"config": {"name": "x"}})
    assert response.status_code != 403
