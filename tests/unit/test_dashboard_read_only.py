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


@pytest.mark.asyncio
async def test_read_only_rejects_policy_path_on_compare_and_lineage_diff(demo_registry: DbRegistry, monkeypatch) -> None:
    client = _client(demo_registry, monkeypatch, "1")
    db_id = client.get("/dbs").json()[0]["db_id"]
    body = {"selections": [{"db_id": db_id, "run_id": "aaaaaaaa"}, {"db_id": db_id, "run_id": "aaaaaaaa"}], "policy_path": "/etc/passwd"}
    assert client.post("/compare", json=body).status_code == 403
    response = client.get(f"/dbs/{db_id}/runs/aaaaaaaa/queries/q1/candidate-lineage-diff", params={"against": "aaaaaaaa", "policy_path": "/etc/passwd"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_read_only_hides_filesystem_paths_and_serves_healthz(demo_registry: DbRegistry, monkeypatch) -> None:
    monkeypatch.setenv("RETOBS_READ_ONLY", "1")
    registry = DbRegistry(demo_registry.db_paths)  # built after the env is set, as `retobs serve` does
    client = _client(registry, monkeypatch, "1")
    assert client.get("/dbs").json()[0]["path"] == "demo.db"
    assert client.get("/healthz").json() == {"status": "ok", "read_only": True, "databases": 1}


@pytest.mark.asyncio
async def test_read_only_store_refuses_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "ro.db"
    await _seed_run(db_path, "bbbbbbbb")
    registry = DbRegistry([str(db_path)], read_only=True)
    store = registry.get_store(registry.default_db_id)
    await store.init_db()
    assert [run["run_id"] for run in await store.list_runs()] == ["bbbbbbbb"]
    with pytest.raises(Exception, match="readonly database"):
        await store.save_run("cccccccc", "exp", "{}")


@pytest.mark.asyncio
async def test_read_only_store_reports_incomplete_schema(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "old.db"
    sqlite3.connect(db_path).execute("CREATE TABLE runs (run_id TEXT)").connection.commit()
    with pytest.raises(RuntimeError, match="missing tables"):
        await SQLiteStore(db_path=str(db_path), read_only=True).init_db()


@pytest.mark.asyncio
async def test_rate_limit_returns_429_per_forwarded_ip(demo_registry: DbRegistry, monkeypatch) -> None:
    monkeypatch.setenv("RETOBS_RATE_LIMIT_PER_MINUTE", "3")
    client = _client(demo_registry, monkeypatch, "1")
    codes = [client.get("/healthz", headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert client.get("/healthz", headers={"x-forwarded-for": "203.0.113.10"}).status_code == 200


@pytest.mark.asyncio
async def test_invalid_query_parameters_are_422_not_500(demo_registry: DbRegistry, monkeypatch) -> None:
    client = _client(demo_registry, monkeypatch, "1")
    db_id = client.get("/dbs").json()[0]["db_id"]
    assert client.get(f"/dbs/{db_id}/production/traces", params={"service_id": "svc", "since": "yesterday"}).status_code == 422
    assert client.get(f"/dbs/{db_id}/production/traces", params={"service_id": "svc", "limit": 0}).status_code == 422
    assert client.get(f"/dbs/{db_id}/runs/aaaaaaaa/query-winners", params={"k": 0}).status_code == 422
