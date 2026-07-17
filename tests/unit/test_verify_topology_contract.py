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
