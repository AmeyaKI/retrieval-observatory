"""``ready`` is evidence: a fabricated span with no candidates, no query, and no time must not pass."""
from __future__ import annotations

from datetime import datetime, timezone

from retrieval_observatory.integrations.manifest import write_manifest
from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping, VerificationScenario
from retrieval_observatory.integrations.verify import verify_observed_traces, verify_project
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def _manifest() -> IntegrationManifest:
    return IntegrationManifest(
        1, "plan-1", "proj_b", "proj_b-retrieval",
        (OperatorMapping("search", "SOURCE", "search", "app/main.py"),),
        {"doc_id": "item.id"},
        (VerificationScenario("representative", "retobs verification query", ("search",)),),
    )


def _fabricated_trace() -> RetrievalTrace:
    """The reviewer's fake_trace.py: a FIRED span with nothing in it used to read as ready."""
    span = OperatorSpan("search", "SOURCE", "search", (), "FIRED", 0.0)
    return RetrievalTrace("fake1", "proj_b", None, "q1", "", "proj_b-retrieval", (span,), ("search",), datetime.now(timezone.utc), timing=TraceTiming(0.0, 0.0, 0.0))


def _real_trace() -> RetrievalTrace:
    candidate = Candidate("d2", 1.0, 1, origin_op_ids=("search",))
    span = OperatorSpan("search", "SOURCE", "search", (), "FIRED", 1.5, outputs=(candidate,))
    return RetrievalTrace("real1", "proj_b", None, "q1", "lexical sparse retriever", "proj_b-retrieval", (span,), ("search",), datetime.now(timezone.utc), timing=TraceTiming(2.0, 1.5, 1.5))


def test_fabricated_empty_trace_is_not_ready() -> None:
    result = verify_observed_traces(_manifest(), [_fabricated_trace()])
    assert result.status == "failed"
    failing = {check.check_id for check in result.checks if check.status == "error"}
    assert {"scenario_evidence", "timing"} <= failing
    assert any("doc_id" in error and "query_text" in error for error in result.errors)


def test_real_trace_without_run_id_is_ready() -> None:
    result = verify_observed_traces(_manifest(), [_real_trace()])
    assert result.status == "ready", result.errors
    assert {check.check_id for check in result.checks} >= {"scenario_evidence", "stable_identity", "candidate_identity", "timing_semantics"}


def test_scenario_requires_every_expected_operator_to_fire() -> None:
    manifest = IntegrationManifest(
        1, "plan-1", "proj_b", "proj_b-retrieval",
        (OperatorMapping("search", "SOURCE", "search", "a.py"), OperatorMapping("rerank", "RERANK", "rerank", "a.py")),
        {"doc_id": "item.id"},
        (VerificationScenario("representative", "q", ("search", "rerank")),),
    )
    result = verify_observed_traces(manifest, [_real_trace()])
    assert result.status == "failed"
    assert any("'representative'" in error and "rerank" in error for error in result.errors)


async def test_no_traces_names_service_pipeline_and_db(tmp_path) -> None:
    write_manifest(tmp_path, _manifest())
    db = str(tmp_path / "traces.db")
    store = SQLiteStore(db_path=db)
    await store.init_db()
    result = await verify_project(tmp_path, store)
    assert result.status == "failed"
    assert "service_id='proj_b'" in result.errors[0]
    assert "pipeline_id='proj_b-retrieval'" in result.errors[0]
    assert db in result.errors[0]


async def test_verify_without_manifest_fails_cleanly(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "traces.db"))
    await store.init_db()
    result = await verify_project(tmp_path, store)
    assert result.status == "failed"
    assert result.errors == ("no retobs/integration.yaml: run apply first",)
