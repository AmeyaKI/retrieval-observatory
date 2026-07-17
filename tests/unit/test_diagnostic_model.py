import pytest

from retrieval_observatory.diagnostics.model import (
    DiagnosticContext,
    DiagnosticEvidence,
    DiagnosticFinding,
    FindingAvailability,
)
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace


def test_finding_roundtrip_preserves_evidence_contract() -> None:
    finding = DiagnosticFinding(
        label="fusion_loss",
        availability=FindingAvailability.SUPPORTED,
        evidence=DiagnosticEvidence(
            evidence_class="measured_candidate_transition",
            method_id="candidate_loss",
            method_version="1.0",
            trace_ids=("trace-1",),
            operator_ids=("fuse",),
            document_ids=("relevant-1",),
            cutoff=10,
            limitations=(),
        ),
    )
    assert DiagnosticFinding.from_dict(finding.to_dict()) == finding


def test_unavailable_finding_requires_reason() -> None:
    with pytest.raises(ValueError, match="unavailable_reason"):
        DiagnosticFinding(label="ranking_failure", availability=FindingAvailability.UNAVAILABLE)


def test_context_rejects_evidence_for_another_trace() -> None:
    trace = RetrievalTrace(
        trace_id="t",
        service_id="s",
        run_id=None,
        query_id="q",
        query_text="q",
        pipeline_id="p",
        spans=[OperatorSpan.source("source", "source", [])],
        final_op_ids=("source",),
    )
    context = DiagnosticContext(trace=trace, relevant_document_ids=frozenset(), cutoff=10)
    finding = DiagnosticFinding(
        label="x",
        availability=FindingAvailability.SUPPORTED,
        evidence=DiagnosticEvidence("measured", "m", "1", trace_ids=("other",)),
    )
    with pytest.raises(ValueError, match="unknown trace"):
        context.validate_finding(finding)
