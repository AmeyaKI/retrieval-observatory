import time

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from retrieval_observatory.tracing import TelemetryConfig, TraceRecorder
from retrieval_observatory.tracing.integrations.fastapi import instrument_fastapi
from retrieval_observatory.tracing.sink import BufferedTraceSink


class _FailingExporter:
    async def export(self, batch) -> None:
        raise RuntimeError("offline")

    async def close(self) -> None:
        return None


def test_exporter_failure_does_not_change_response_or_wait() -> None:
    sink = BufferedTraceSink(
        _FailingExporter(),
        TelemetryConfig(max_retries=0, export_timeout_s=0.01),
        service_id="svc",
    )
    recorder = TraceRecorder("svc", sink)
    app = FastAPI()
    instrument_fastapi(app, recorder)

    @app.post("/retrieve")
    async def retrieve():
        return {"ids": ["doc-1"]}

    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.post("/retrieve", json={"query": "reset password"})
        elapsed = time.perf_counter() - started
        assert response.status_code == 200
        assert response.json() == {"ids": ["doc-1"]}
        assert elapsed < 0.1
        client.portal.call(sink.flush, 1)
        assert app.state.retobs.health().permanent_failures >= 1
