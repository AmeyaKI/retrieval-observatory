from retrieval_observatory.diagnostics import DiagnosticEngine, FindingAvailability, context_for_trace
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def test_gated_hybrid_diagnostics_preserve_factual_boundaries() -> None:
    gate = OperatorSpan("gate", "GATE", "router", (), "FIRED", .1, gate_values={"route": "general"})
    dense = OperatorSpan.source("dense", "dense", [Candidate("gold", .9, 1)], ("gate",))
    skipped = OperatorSpan("temporal", "SOURCE", "temporal", ("gate",), "SKIPPED_BY_GATE", 0)
    fuse = OperatorSpan(
        "fuse", "FUSE", "rrf", ("dense", "temporal"), "FIRED", 1,
        {"dense": dense.outputs, "temporal": ()}, (),
    )
    trace = RetrievalTrace("t", "svc", "run", "q", "q", "hybrid", (gate, dense, skipped, fuse), ("fuse",))
    findings = {f.label: f for f in DiagnosticEngine.default().evaluate(
        context_for_trace(trace, relevant_document_ids={"gold"}, corpus_document_ids={"gold"}, cutoff=10)
    )}
    assert findings["fusion_loss"].availability is FindingAvailability.SUPPORTED
    assert findings["gate_exclusion"].availability is FindingAvailability.LIMITED
    assert findings["ranking_failure"].availability is FindingAvailability.NOT_OBSERVED
