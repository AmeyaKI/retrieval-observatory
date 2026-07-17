from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.base import InstrumentationHealth
from retrieval_observatory.store.sqlite import SQLiteStore


@pytest.mark.asyncio
async def test_instrumentation_health_endpoint_returns_measured_snapshot(tmp_path) -> None:
    db_path = tmp_path / "health.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    observed_at = datetime.now(timezone.utc)
    await store.save_instrumentation_health(
        InstrumentationHealth(
            service_id="search-api",
            accepted=10,
            exported=8,
            dropped=2,
            drop_reasons={"queue_full": 2},
            sample_rate=0.5,
            observed_at=observed_at,
            last_export_at=observed_at,
            last_flush_latency_ms=12.5,
        )
    )

    client = TestClient(create_app(registry=DbRegistry([str(db_path)]), enable_uploads=False))
    db_id = client.get("/dbs").json()[0]["db_id"]
    response = client.get(f"/dbs/{db_id}/production/services/search-api/instrumentation-health")

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_class"] == "measured"
    assert body["sample_size"] == 10
    assert body["drop_reasons"] == {"queue_full": 2}
    assert body["last_flush_latency_ms"] == 12.5
    assert body["limitations"] == ["sampled capture"]


@pytest.mark.asyncio
async def test_instrumentation_health_endpoint_marks_missing_snapshot_unavailable(tmp_path) -> None:
    db_path = tmp_path / "health.db"
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    client = TestClient(create_app(registry=DbRegistry([str(db_path)]), enable_uploads=False))
    db_id = client.get("/dbs").json()[0]["db_id"]

    body = client.get(f"/dbs/{db_id}/production/services/missing/instrumentation-health").json()

    assert body["evidence_class"] == "unavailable"
    assert body["unavailable_reason"] == "no instrumentation health snapshot"
