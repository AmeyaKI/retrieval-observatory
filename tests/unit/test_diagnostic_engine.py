from retrieval_observatory.diagnostics import DiagnosticEngine, FindingAvailability, context_for_trace
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def _trace(*, truncated: bool = False) -> RetrievalTrace:
    dense = OperatorSpan.source("dense", "dense", [Candidate("gold", .9, 1)])
    sparse = OperatorSpan.source("sparse", "sparse", [Candidate("other", .8, 1)])
    fuse = OperatorSpan(
        "fuse", "FUSE", "rrf", ("dense", "sparse"), "FIRED", 1,
        {"dense": dense.outputs, "sparse": sparse.outputs}, (Candidate("other", .8, 1),),
    )
    return RetrievalTrace("trace", "svc", "run", "query", "q", "pipe", (dense, sparse, fuse), ("fuse",))


def test_engine_returns_one_valid_result_per_registered_rule() -> None:
    context = context_for_trace(_trace(), relevant_document_ids={"gold"}, corpus_document_ids={"gold", "other"})
    engine = DiagnosticEngine.default()
    findings = engine.evaluate(context)
    assert tuple(f.label for f in findings) == engine.rule_labels
    assert next(f for f in findings if f.label == "fusion_loss").availability is FindingAvailability.SUPPORTED
    assert next(f for f in findings if f.label == "branch_specific_miss").availability is FindingAvailability.SUPPORTED


def test_unlabeled_trace_never_emits_quality_failure() -> None:
    findings = DiagnosticEngine.default().evaluate(context_for_trace(_trace()))
    assert all(f.availability is not FindingAvailability.SUPPORTED for f in findings)
