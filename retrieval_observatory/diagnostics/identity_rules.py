from __future__ import annotations

from retrieval_observatory.diagnostics.helpers import RuleBase, finding
from retrieval_observatory.diagnostics.model import DiagnosticContext, FindingAvailability


class QrelAbsentFromCorpusRule(RuleBase):
    label = "qrel_absent_from_corpus"

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        if not context.relevant_document_ids:
            return self.unavailable("ground_truth_missing")
        if context.corpus_document_ids is None:
            return self.unavailable("corpus_identity_missing")
        missing = context.relevant_document_ids - context.corpus_document_ids
        return finding(self, FindingAvailability.SUPPORTED, documents=missing) if missing else self.not_observed()


class SourceMissRule(RuleBase):
    label = "source_miss"

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        if not context.relevant_document_ids:
            return self.unavailable("ground_truth_missing")
        if not context.capture_complete:
            return self.unavailable("candidate_capture_incomplete")
        sources = [span for span in context.trace.spans if span.op_type == "SOURCE" and span.status == "FIRED"]
        if not sources:
            return self.unavailable("source_candidates_missing")
        output_ids = {candidate.doc_id for span in sources for candidate in span.outputs}
        missed = context.relevant_document_ids - output_ids
        return finding(self, FindingAvailability.SUPPORTED, documents=missed, operators=(s.op_id for s in sources)) if missed else self.not_observed()
