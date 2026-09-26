"""Retired dashboard routes answer 410 with a migration message; retained workflows still answer."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard import api as dashboard_api
from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore

REPLACEMENTS = {"#/investigate", "#/audit", "#/connect"}


@pytest.fixture
def client_and_db(tmp_path: Path) -> tuple[TestClient, str]:
    path = str(tmp_path / "retired.db")
    asyncio.run(SQLiteStore(path).init_db())
    registry = DbRegistry([path])  # single database: the unprefixed legacy paths are live too
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    return client, registry.default_db_id


def _retired_paths(db: str) -> list[tuple[str, str]]:
    run = "/runs/r1"
    paths = []
    for prefix in (f"/dbs/{db}", ""):
        paths += [
            ("GET", f"{prefix}/forge/datasets"),
            ("GET", f"{prefix}/forge/datasets/ds1/queries"),
            ("GET", f"{prefix}/advisor/recommendations?run_id=r1"),
            ("GET", f"{prefix}/advisor/reliability/history?run_id=r1"),
            ("GET", f"{prefix}{run}/query-labels"),
            ("GET", f"{prefix}{run}/classifier-calibration"),
            ("GET", f"{prefix}{run}/pareto-frontier"),
            ("GET", f"{prefix}{run}/operator-attribution?metric=recall&k=10"),
            ("GET", f"{prefix}{run}/traces/t1/miss-attribution"),
            ("GET", f"{prefix}{run}/traces/t1/operator/op1/diff"),
            ("GET", f"{prefix}{run}/queries/q1/candidates/d1"),
        ]
        paths += [("GET", f"{prefix}/production/{view}?service_id=svc") for view in (
            "summary", "distribution", "drift", "hotspots", "clusters",
        )]
    paths += [
        ("GET", f"/dbs/{db}/analysis/cohorts"),
        ("POST", f"/dbs/{db}/analysis/cohorts"),
        ("GET", f"/dbs/{db}/analysis/corpus-health"),
    ]
    return paths


def test_every_retired_route_answers_410_with_a_replacement(client_and_db) -> None:
    client, db = client_and_db
    for method, path in _retired_paths(db):
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 410, (method, path, response.status_code)
        detail = response.json()["detail"]
        assert detail["code"] == "retired", path
        assert detail["replacement"] in REPLACEMENTS, path
        assert detail["detail"], path


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/dbs/{db}/runs", None),
        ("GET", "/dbs/{db}/integrations", None),
        ("GET", "/dbs/{db}/investigation/runs/r1/queries", None),
        ("POST", "/compare", {"selections": []}),
        ("GET", "/dbs/{db}/production/services", None),
        ("GET", "/dbs/{db}/production/traces?service_id=svc", None),
        ("GET", "/dbs/{db}/analysis/gates", None),
    ],
)
def test_retained_routes_still_answer(client_and_db, method: str, path: str, body) -> None:
    client, db = client_and_db
    response = client.request(method, path.format(db=db), json=body)
    assert response.status_code not in (405, 410), (path, response.status_code)
    assert response.headers["content-type"].startswith("application/json"), path


def test_dashboard_routes_import_no_retired_module() -> None:
    sources = [
        Path(dashboard_api.__file__).read_text(encoding="utf-8"),
        (Path(dashboard_api.__file__).parent / "analysis_api.py").read_text(encoding="utf-8"),
    ]
    for retired in (
        "metrics.pareto",
        "tracing.attribution",
        "tracing.replay",
        "analysis.cohorts",
        "analysis.corpus_health",
        "analysis.service",
        "tracing.monitor.drift",
        "tracing.monitor.hotspots",
        "tracing.monitor.cluster",
        "retrieval_observatory.experimental",
    ):
        for source in sources:
            assert retired not in source, retired
