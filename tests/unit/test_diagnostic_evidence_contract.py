from retrieval_observatory.diagnostics import DiagnosticEngine, FindingAvailability, context_for_trace
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def test_ranking_failure_requires_relevant_document_below_cutoff() -> None:
    final = OperatorSpan.source(
        "final", "final", [Candidate("other", 1, 1), Candidate("gold", .5, 11)]
    )
    trace = RetrievalTrace("t", "svc", "run", "q", "q", "p", (final,), ("final",))
    finding = next(
        item for item in DiagnosticEngine.default().evaluate(
            context_for_trace(trace, relevant_document_ids={"gold"}, cutoff=10)
        ) if item.label == "ranking_failure"
    )
    assert finding.availability is FindingAvailability.SUPPORTED
    assert finding.evidence.cutoff == 10


def test_pretruncated_final_ranking_is_unavailable() -> None:
    final = OperatorSpan(
        "final", "RERANK", "final", (), "FIRED", 1, outputs=(Candidate("other", 1, 1),), params={"top_k": 10}
    )
    trace = RetrievalTrace("t", "svc", "run", "q", "q", "p", (final,), ("final",))
    finding = next(item for item in DiagnosticEngine.default().evaluate(
        context_for_trace(trace, relevant_document_ids={"gold"}, cutoff=10)
    ) if item.label == "ranking_failure")
    assert finding.availability is FindingAvailability.UNAVAILABLE
    assert finding.unavailable_reason == "pre_truncation_ranking_not_captured"
