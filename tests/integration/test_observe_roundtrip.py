from __future__ import annotations

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace


@observe("SOURCE", op_id="retrieve", deterministic=True, replay_policy="EXACT")
def source_step() -> list[str]:
    return ["d1", "d2", "d3"]


def test_observe_roundtrip(tmp_path):
    db_path = tmp_path / "observe.db"
    app = create_app(registry=DbRegistry([str(db_path)]), enable_uploads=False)
    with TestClient(app) as client:
        run_resp = client.post("/experiments/demo/runs", json={"config_json": "{}"})
        assert run_resp.status_code == 200
        run_id = run_resp.json()["run_id"]

        start_trace(
            ObserveContext(
                run_id=run_id,
                query_id="q1",
                query_text="cats",
                pipeline_id="demo_pipeline",
            )
        )
        source_step()
        trace = finish_trace()

        ingest_resp = client.post(f"/runs/{run_id}/traces", json=trace.to_dict())
        assert ingest_resp.status_code == 200
        trace_id = ingest_resp.json()["trace_id"]

        get_resp = client.get(f"/runs/{run_id}/traces/{trace_id}")
        assert get_resp.status_code == 200
        payload = get_resp.json()
        assert payload["schema_version"] == 1
        assert payload["query_id"] == "q1"
