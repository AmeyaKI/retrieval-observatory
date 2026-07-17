from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry


def _make_trace_payload(run_id: str, query_id: str = "q1") -> dict:
    return {
        "trace_id": uuid.uuid4().hex[:16],
        "run_id": run_id,
        "query_id": query_id,
        "query_text": "test query",
        "pipeline_id": "pipe_a",
        "trace_format_version": 2,
        "total_latency_ms": 42.0,
        "status": "OK",
        "spans": [
            {
                "op_id": "bm25",
                "op_type": "SOURCE",
                "op_name": "bm25",
                "parent_ids": [],
                "status": "FIRED",
                "deterministic": True,
                "replay_policy": "EXACT",
                "latency_ms": 42.0,
                "inputs": [],
                "outputs": [
                    {"doc_id": "d1", "score": 0.9, "rank": 1},
                    {"doc_id": "d2", "score": 0.7, "rank": 2},
                ],
            }
        ],
    }


def test_v2_trace_ingest_and_get(tmp_path):
    db_path = tmp_path / "roundtrip.db"
    app = create_app(registry=DbRegistry([str(db_path)]), enable_uploads=False)
    with TestClient(app) as client:
        run_resp = client.post("/experiments/roundtrip/runs", json={"config_json": "{}"})
        assert run_resp.status_code == 200
        run_id = run_resp.json()["run_id"]

        trace_payload = _make_trace_payload(run_id, query_id="q1")
        ingest_resp = client.post(f"/runs/{run_id}/traces", json=trace_payload)
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["stored"] is True
        trace_id = ingest_resp.json()["trace_id"]

        get_resp = client.get(f"/runs/{run_id}/traces/{trace_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["schema_version"] == 1
        assert data["query_id"] == "q1"
        assert data["pipeline_id"] == "pipe_a"
        assert len(data["spans"]) == 1
        assert data["spans"][0]["op_id"] == "bm25"
        assert len(data["spans"][0]["outputs"]) == 2


def test_v2_trace_list(tmp_path):
    db_path = tmp_path / "roundtrip_list.db"
    app = create_app(registry=DbRegistry([str(db_path)]), enable_uploads=False)
    with TestClient(app) as client:
        run_resp = client.post("/experiments/roundtrip/runs", json={"config_json": "{}"})
        run_id = run_resp.json()["run_id"]

        for qid in ("q1", "q2"):
            resp = client.post(f"/runs/{run_id}/traces", json=_make_trace_payload(run_id, query_id=qid))
            assert resp.status_code == 200

        list_resp = client.get(f"/runs/{run_id}/traces")
        assert list_resp.status_code == 200
        traces = list_resp.json()
        assert len(traces) == 2
        query_ids = {t["query_id"] for t in traces}
        assert query_ids == {"q1", "q2"}


def test_batch_results_ingest(tmp_path):
    db_path = tmp_path / "roundtrip_batch.db"
    app = create_app(registry=DbRegistry([str(db_path)]), enable_uploads=False)
    with TestClient(app) as client:
        run_resp = client.post("/experiments/roundtrip/runs", json={"config_json": "{}"})
        run_id = run_resp.json()["run_id"]

        traces = [_make_trace_payload(run_id, query_id=f"q{i}") for i in range(3)]
        resp = client.post(f"/runs/{run_id}/results", json={"traces": traces})
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 3

        list_resp = client.get(f"/runs/{run_id}/traces")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 3
