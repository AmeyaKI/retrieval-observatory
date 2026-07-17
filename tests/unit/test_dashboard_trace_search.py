from fastapi.testclient import TestClient
import pytest

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace


@pytest.mark.asyncio
async def test_production_trace_search_returns_page_envelope(tmp_path):
    path = tmp_path / "trace.db"
    store = SQLiteStore(str(path))
    await store.init_db()
    for index in range(3):
        await store.save_trace(
            RetrievalTrace(
                f"t{index}", "svc", None, f"q{index}", "q", "p", (OperatorSpan.source("source", "source", ()),), ("source",)
            )
        )
    client = TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))
    db = client.get("/dbs").json()[0]["db_id"]
    body = client.get(f"/dbs/{db}/production/traces?service_id=svc&limit=2").json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["next_offset"] == 2
