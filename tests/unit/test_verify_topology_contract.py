from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping
from retrieval_observatory.integrations.verify import verify_trace_contract
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def _manifest():
    return IntegrationManifest(
        1, "plan", "service", "pipeline",
        (
            OperatorMapping("source", "SOURCE", "source", "app.py"),
            OperatorMapping("final", "RERANK", "final", "app.py", ("source",)),
        ),
        {"doc_id": "id"}, (),
    )


def _trace(final_id="final"):
    candidate = Candidate("d", 1.0, 1, origin_op_ids=("source",))
    return RetrievalTrace(
        trace_id="trace", service_id="service", run_id="run", query_id="query",
        query_text="query", pipeline_id="pipeline", spans=(
            OperatorSpan("source", "SOURCE", "source", (), "FIRED", 1.0, outputs=(candidate,)),
            OperatorSpan(final_id, "RERANK", "final", ("source",), "FIRED", 1.0,
                         input_groups={"source": (candidate,)}, outputs=(candidate,)),
        ),
        final_op_ids=(final_id,),
    )


def test_verification_fails_random_operator_identity() -> None:
    report = verify_trace_contract(_manifest(), [_trace("random-final")])
    assert report.check("topology_identity").status == "error"
    assert report.check("unknown_components").details["unknown"] == ["random-final"]


def test_verification_accepts_manifest_faithful_trace() -> None:
    assert verify_trace_contract(_manifest(), [_trace()]).ready


def test_trace_lacking_a_declared_operator_is_not_topology_drift() -> None:
    """A conditional operator that did not fire for this query is a route matter, not drift."""
    candidate = Candidate("d", 1.0, 1, origin_op_ids=("source",))
    trace = RetrievalTrace(
        trace_id="trace", service_id="service", run_id="run", query_id="query",
        query_text="query", pipeline_id="pipeline",
        spans=(OperatorSpan("source", "SOURCE", "source", (), "FIRED", 1.0, outputs=(candidate,)),),
        final_op_ids=("source",),
    )
    report = verify_trace_contract(_manifest(), [trace])
    assert report.check("topology_identity").status == "ok"
    assert "missing_by_trace" not in report.check("topology_identity").details
    assert report.ready
