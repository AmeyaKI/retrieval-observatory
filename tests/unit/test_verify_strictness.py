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
    assert {"candidate_identity", "query_identity", "declared_route_coverage"} <= failing
    assert result.capabilities["candidate_identity"]["status"] == "unavailable"
    assert result.capabilities["query_identity"]["status"] == "unavailable"
    assert any("doc_id" in error for error in result.errors)
    assert any("query_text" in error for error in result.errors)


def test_real_trace_without_run_id_is_a_limitation_not_a_failure() -> None:
    """One trace with no labels: every observed capability is ready, the unobservable ones
    (labels, a repeated query) are named, and the integration is partial rather than failed."""
    result = verify_observed_traces(_manifest(), [_real_trace()])
    assert result.status == "partial", result.errors
    assert result.errors == ()
    for name in ("topology_observed", "actual_input_output_capture", "candidate_identity", "query_identity", "final_output_capture", "declared_route_coverage"):
        assert result.capabilities[name]["status"] == "ready", (name, result.capabilities[name]["failures"])
    assert result.capabilities["judgment_mapping"]["status"] == "unavailable"
    assert result.capabilities["cross_run_entity_alignment"]["status"] == "partial"
    assert [check.check_id for check in result.checks] == list(result.capabilities)


def test_scenario_requires_every_expected_operator_to_fire() -> None:
    manifest = IntegrationManifest(
        1, "plan-1", "proj_b", "proj_b-retrieval",
        (OperatorMapping("search", "SOURCE", "search", "a.py"), OperatorMapping("rerank", "RERANK", "rerank", "a.py")),
        {"doc_id": "item.id"},
        (VerificationScenario("representative", "q", ("search", "rerank")),),
    )
    result = verify_observed_traces(manifest, [_real_trace()])
    assert result.status == "partial"
    coverage = result.capabilities["declared_route_coverage"]
    assert coverage["status"] == "unavailable"
    assert coverage["evidence"]["missing_by_scenario"] == {"representative": ["rerank"]}
    [failure] = coverage["failures"]
    assert failure["code"] == "scenario_unobserved"
    assert "'representative'" in failure["detail"] and "rerank" in failure["detail"]


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
