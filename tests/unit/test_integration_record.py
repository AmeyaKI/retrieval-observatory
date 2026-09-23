"""Verify persists an integration record; Connect reads it and links the first investigation."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.integrations.model import CAPABILITY_NAMES, IntegrationOptions, IntegrationPhase, OperatorMapping
from retrieval_observatory.integrations.planner import build_integration_plan
from retrieval_observatory.integrations.record import (
    INTEGRATION_RECORD_KIND,
    get_integration_record,
    integration_depth,
    save_integration_record,
)
from retrieval_observatory.integrations.service import integrate_project
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import materialize  # noqa: E402


def _trace(service_id: str, pipeline_id: str, op_id: str, query_id: str = "q1") -> RetrievalTrace:
    candidate = Candidate("d2", 1.0, 1, origin_op_ids=(op_id,))
    span = OperatorSpan(op_id, "SOURCE", op_id, (), "FIRED", 1.5, outputs=(candidate,))
    return RetrievalTrace(
        f"trace-{query_id}", service_id, None, query_id, "lexical sparse retriever", pipeline_id, (span,), (op_id,),
        datetime.now(timezone.utc), timing=TraceTiming(2.0, 1.5, 1.5),
    )


async def test_verify_persists_integration_record_and_versions(tmp_path: Path) -> None:
    root = materialize("proj_a", tmp_path)
    plan = build_integration_plan(root)
    plan_path = root / "retobs" / "integration-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({"plan": plan.to_dict()}), encoding="utf-8")
    await integrate_project(root, IntegrationPhase.APPLY, IntegrationOptions(plan=plan))
    store = SQLiteStore(db_path=str(root / ".retobs" / "results.db"))
    await store.init_db()
    await store.save_trace(_trace(plan.service_id, plan.pipeline_id, plan.operators[0].op_id))

    result = await integrate_project(root, IntegrationPhase.VERIFY, IntegrationOptions())
    record = await get_integration_record(store, f"{plan.service_id}:{plan.pipeline_id}")

    assert record is not None and record["version"] == 1
    assert record["status"] == result.status
    assert record["plan_id"] == plan.plan_id
    assert set(record["capabilities"]) == set(CAPABILITY_NAMES)
    assert record["depth"] == "final_only"
    assert [action["kind"] for action in record["actions"]][:1] == ["install"]
    assert record["open_questions"] == list(plan.open_questions)
    assert record["scenarios"][0]["command"] == plan.scenarios[0].command
    assert json.dumps(record)  # JSON-safe end to end

    await integrate_project(root, IntegrationPhase.VERIFY, IntegrationOptions())
    again = await get_integration_record(store, f"{plan.service_id}:{plan.pipeline_id}")
    assert again is not None and again["version"] == 2


def test_integration_depth_classifies_final_only_and_internal() -> None:
    source = OperatorMapping("http_endpoint", "SOURCE", "search", "app.py")
    assert integration_depth([source]) == "final_only"
    assert integration_depth([source, OperatorMapping("rerank", "RERANK", "rerank", "app.py", ("http_endpoint",))]) == "internal"


async def _seed(db_path: Path, *, run_pipeline: str | None) -> None:
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    if run_pipeline:
        await store.save_run("run-1", "exp", json.dumps({}))
        await store.save_run_manifest("run-1", {"normalized_config": {"pipelines": [{"id": run_pipeline}]}})
        await store.finish_run("run-1")
    await save_integration_record(store, {
        "integration_id": "svc:pipe-x", "service_id": "svc", "pipeline_id": "pipe-x", "plan_id": "plan-1",
        "status": "partial", "depth": "internal", "verified_at": "2026-09-23T00:00:00+00:00",
        "capabilities": {name: {"status": "ready", "evidence": {}, "scope": "", "failures": []} for name in CAPABILITY_NAMES},
        "operators": [], "scenarios": [], "actions": [], "open_questions": [], "unresolved": [],
    })


async def test_integration_endpoints_list_and_link_first_run(tmp_path: Path) -> None:
    db_path = tmp_path / "results.db"
    await _seed(db_path, run_pipeline="pipe-x")
    registry = DbRegistry([str(db_path)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    base = f"/dbs/{registry.default_db_id}/integrations"

    listed = client.get(base)
    assert listed.status_code == 200, listed.text
    assert [item["integration_id"] for item in listed.json()["integrations"]] == ["svc:pipe-x"]
    assert listed.json()["integrations"][0]["status"] == "partial"

    detail = client.get(f"{base}/svc:pipe-x")
    assert detail.status_code == 200, detail.text
    assert detail.json()["investigation"] == {"run_id": "run-1", "pipeline_id": "pipe-x"}
    assert set(detail.json()["capabilities"]) == set(CAPABILITY_NAMES)

    assert client.get(f"{base}/nope:none").status_code == 404


async def test_integration_without_a_run_has_no_investigation_link(tmp_path: Path) -> None:
    db_path = tmp_path / "results.db"
    await _seed(db_path, run_pipeline=None)
    registry = DbRegistry([str(db_path)])
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    detail = client.get(f"/dbs/{registry.default_db_id}/integrations/svc:pipe-x")
    assert detail.status_code == 200, detail.text
    assert detail.json()["investigation"] is None
    store = SQLiteStore(db_path=str(db_path))
    assert (await store.list_analysis_records(INTEGRATION_RECORD_KIND))[0]["record_id"] == "svc:pipe-x"
