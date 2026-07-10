from __future__ import annotations

import pytest

from retrieval_observatory.integrations.verify import _integration_checks, verify_integration
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2


def _trace(qid, *, query_text="q", status="OK"):
    src = OperatorSpan(
        op_id="src", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["src"])],
    )
    return RetrievalTraceV2(trace_id=f"t{qid}", run_id="r", query_id=qid, query_text=query_text,
                            pipeline_id="p", spans=[src], total_latency_ms=1.0, status=status,
                            final_op_id="src")


def test_checks_all_green_on_healthy_traces():
    checks = _integration_checks([_trace(f"q{i}") for i in range(3)])
    assert {c["name"] for c in checks} >= {"traces_present", "query_text_metadata", "candidate_scores",
                                           "supported_operators", "trace_health"}
    assert all(c["status"] == "ok" for c in checks)


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
    await store.save_trace_v2(_trace("q0"))
    report = await verify_integration(db_path=str(db), run_id="r")
    assert "checks" in report
    assert report["check_status"] == "ok"
