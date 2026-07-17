from __future__ import annotations

import pytest

from retrieval_observatory.integrations.verify import _integration_checks, verify_integration
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def _trace(qid, *, query_text="q", status="OK"):
    src = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    return RetrievalTrace(trace_id=f"t{qid}", service_id="svc", run_id="r", query_id=qid, query_text=query_text,
                            pipeline_id="p", spans=[src], timing=TraceTiming(1.0, 1.0, 1.0), status=status,
                            final_op_ids=("src",), metadata={"label_method": "human"})


def test_checks_all_green_on_healthy_traces():
    checks = _integration_checks([_trace(f"q{i}") for i in range(3)])
    assert {c["name"] for c in checks} >= {"traces_present", "query_text_metadata", "candidate_identity",
                                           "supported_operators", "trace_health"}
    assert not any(c["status"] == "error" for c in checks)


def test_no_traces_is_error():
    checks = _integration_checks([])
    assert checks[0]["name"] == "traces_present"
    assert checks[0]["status"] == "error"


def test_missing_query_text_warns():
    checks = _integration_checks([_trace("q0", query_text="")])
    qt = next(c for c in checks if c["name"] == "query_text_metadata")
    assert qt["status"] == "warn"


def test_error_trace_flags_health():
    checks = _integration_checks([_trace("q0", status="ERROR")])
    health = next(c for c in checks if c["name"] == "trace_health")
    assert health["status"] == "warn"


@pytest.mark.asyncio
async def test_verify_integration_reports_check_status(tmp_path):
    db = tmp_path / "v.db"
    store = SQLiteStore(db_path=str(db))
    await store.init_db()
    await store.save_run("r", "exp", "{}")
    await store.save_trace(_trace("q0"))
    report = await verify_integration(db_path=str(db), run_id="r")
    assert "checks" in report
    assert report["status"] == "partially_instrumented"
    assert report["check_status"] == "warn"
    assert report["capabilities"]["basic_tracing"]["status"] == "ready"


@pytest.mark.asyncio
async def test_verify_integration_required_error_is_failed(tmp_path):
    db = tmp_path / "invalid.db"
    store = SQLiteStore(db_path=str(db))
    await store.init_db()
    await store.save_run("r", "exp", "{}")
    trace = _trace("q0")
    trace.final_op_ids = ()
    await store.save_trace(trace)
    report = await verify_integration(db_path=str(db), run_id="r")
    assert report["status"] == "failed"
    assert report["capabilities"]["pipeline_graph"]["status"] == "unavailable"
