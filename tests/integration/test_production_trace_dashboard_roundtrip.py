from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace


def test_production_trace_is_visible_without_run(tmp_path) -> None:
    path = tmp_path / "production.db"
    trace = RetrievalTrace(
        trace_id="production-1",
        service_id="search",
        run_id=None,
        query_id="q1",
        query_text="query",
        pipeline_id="hybrid",
        spans=(OperatorSpan.source("source", "Source", ()),),
        final_op_ids=("source",),
        timestamp=datetime.now(timezone.utc),
    )
    client = TestClient(create_app(registry=DbRegistry([str(path)]), enable_uploads=False))
    assert client.post("/production/traces", json=trace.to_dict()).json() == {"ingested": 1}
    services = client.get("/production/services").json()
    traces = client.get("/production/traces", params={"service_id": "search"}).json()
    assert services[0]["service_id"] == "search"
    assert traces["items"][0]["trace_id"] == "production-1"
    assert traces["items"][0]["run_id"] is None
