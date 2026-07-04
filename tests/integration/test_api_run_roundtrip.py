"""P1.2 — REST trigger -> status -> read -> diagram roundtrip via TestClient."""
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def _client(db_path: str):
    """Return a TestClient context manager so FastAPI lifespan (registry.init_all) runs."""
    from fastapi.testclient import TestClient

    from retrieval_observatory.dashboard.api import create_app

    return TestClient(create_app(db_paths=[db_path]))


def _bm25_config() -> dict:
    return {
        "experiment": {"name": "api-roundtrip"},
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }


def test_trigger_wait_and_read(tmp_path):
    db_path = str(tmp_path / "api.db")
    with _client(db_path) as client:
        db_id = client.get("/dbs").json()[0]["db_id"]

        resp = client.post(f"/dbs/{db_id}/runs", json={"config": _bm25_config(), "wait": True, "max_queries": 5})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "completed"
        run_id = body["run_id"]
        assert body["metrics"]

        status = client.get(f"/dbs/{db_id}/runs/{run_id}/status")
        assert status.status_code == 200
        assert status.json()["status"] == "completed"

        diagram = client.get(f"/dbs/{db_id}/runs/{run_id}/diagram")
        assert diagram.status_code == 200
        pipelines = diagram.json()["pipelines"]
        assert pipelines[0]["pipeline_id"] == "bm25"
        node = pipelines[0]["nodes"][0]
        assert node["metrics"]["recall"]["ci_low"] is not None


def test_bad_config_rejected(tmp_path):
    db_path = str(tmp_path / "bad.db")
    with _client(db_path) as client:
        db_id = client.get("/dbs").json()[0]["db_id"]
        resp = client.post(f"/dbs/{db_id}/runs", json={"config": {"not": "valid"}})
        assert resp.status_code == 422


def test_auth_required_when_token_set(tmp_path, monkeypatch):
    monkeypatch.setenv("RETOBS_API_TOKEN", "secret")
    db_path = str(tmp_path / "auth.db")
    with _client(db_path) as client:
        db_id = client.get("/dbs").json()[0]["db_id"]
        # No Authorization header -> 401 on the gated run endpoint.
        resp = client.post(f"/dbs/{db_id}/runs", json={"config": _bm25_config(), "wait": True, "max_queries": 2})
        assert resp.status_code == 401
        # Correct token -> allowed.
        ok = client.post(
            f"/dbs/{db_id}/runs",
            json={"config": _bm25_config(), "wait": True, "max_queries": 2},
            headers={"Authorization": "Bearer secret"},
        )
        assert ok.status_code == 200
