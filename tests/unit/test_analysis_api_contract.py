from fastapi.testclient import TestClient
from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from tests.fixtures.analysis_fixtures import make_trace, source_span
import asyncio


def client(tmp_path):
    path = str(tmp_path / "analysis.db")
    asyncio.run(SQLiteStore(path).init_db())
    api = TestClient(create_app(registry=DbRegistry([path]), enable_uploads=False))
    db = api.get("/dbs").json()[0]["db_id"]
    return api, db


def test_missing_analysis_evidence_is_200_unavailable(tmp_path):
    api, db = client(tmp_path)
    response = api.get(f"/dbs/{db}/analysis/gates")
    assert response.status_code == 200 and response.json()["state"] == "unavailable"


def test_invalid_cohort_is_422(tmp_path):
    api, db = client(tmp_path)
    response = api.post(
        f"/dbs/{db}/analysis/cohorts",
        json={"cohort_id": "bad", "name": "bad", "clauses": [{"field": "__class__", "operator": "eq", "value": "x"}]},
    )
    assert response.status_code == 422


def test_unknown_database_is_404(tmp_path):
    api, _ = client(tmp_path)
    assert api.get("/dbs/missing/analysis/gates").status_code == 404


def test_latency_analysis_is_ready_with_unified_trace(tmp_path):
    path = str(tmp_path / "ready.db")
    store = SQLiteStore(path)
    asyncio.run(store.init_db())
    asyncio.run(store.save_trace(make_trace(spans=(source_span(),))))
    api = TestClient(create_app(registry=DbRegistry([path]), enable_uploads=False))
    db = api.get("/dbs").json()[0]["db_id"]
    response = api.get(f"/dbs/{db}/analysis/latency", params={"run_id": "r1"})
    assert response.status_code == 200 and response.json()["state"] == "ready"
