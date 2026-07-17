from __future__ import annotations

from retrieval_observatory.diagnostics.helpers import RuleBase, finding
from retrieval_observatory.diagnostics.model import DiagnosticContext, FindingAvailability


class _TransitionLossRule(RuleBase):
    op_type = ""

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        if not context.relevant_document_ids:
            return self.unavailable("ground_truth_missing")
        spans = [span for span in context.trace.spans if span.op_type == self.op_type and span.status == "FIRED"]
        if not spans:
            return self.not_observed()
        if any(span.parent_ids and not span.input_groups for span in spans):
            return self.unavailable("pre_transition_candidates_missing")
        removed = set()
        implicated = []
        for span in spans:
            inputs = {c.doc_id for group in span.input_groups.values() for c in group}
            outputs = {c.doc_id for c in span.outputs}
            lost = (inputs - outputs) & context.relevant_document_ids
            if lost:
                removed.update(lost)
                implicated.append(span.op_id)
        return finding(self, FindingAvailability.SUPPORTED, documents=removed, operators=implicated) if removed else self.not_observed()


class FusionLossRule(_TransitionLossRule):
    label, op_type = "fusion_loss", "FUSE"


class FilterLossRule(_TransitionLossRule):
    label, op_type = "filter_loss", "FILTER"


class RerankerLossRule(_TransitionLossRule):
    label, op_type = "reranker_loss", "RERANK"


class TruncationLossRule(RuleBase):
    label = "truncation_loss"

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        spans = [span for span in context.trace.spans if span.params.get("top_k") is not None]
        if not spans:
            return self.not_observed()
        removed = set()
        for span in spans:
            inputs = {c.doc_id for group in span.input_groups.values() for c in group}
            outputs = {c.doc_id for c in span.outputs}
            removed.update((inputs - outputs) & context.relevant_document_ids)
        return finding(self, FindingAvailability.SUPPORTED, documents=removed, operators=(s.op_id for s in spans)) if removed else self.not_observed()


class FinalRankingFailureRule(RuleBase):
    label = "ranking_failure"

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        if not context.relevant_document_ids:
            return self.unavailable("ground_truth_missing")
        finals = [span for span in context.trace.spans if span.op_id in context.trace.final_op_ids]
        if not finals:
            return self.unavailable("final_candidates_missing")
        if any(span.params.get("top_k") == context.cutoff for span in finals):
            return self.unavailable("pre_truncation_ranking_not_captured")
        below = {c.doc_id for span in finals for c in span.outputs if c.rank > context.cutoff} & context.relevant_document_ids
        return finding(self, FindingAvailability.SUPPORTED, documents=below, operators=(s.op_id for s in finals)) if below else self.not_observed()
