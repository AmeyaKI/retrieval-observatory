from __future__ import annotations

from retrieval_observatory.diagnostics.helpers import RuleBase, finding
from retrieval_observatory.diagnostics.model import DiagnosticContext, FindingAvailability


class BranchSpecificMissRule(RuleBase):
    label = "branch_specific_miss"

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        if not context.relevant_document_ids:
            return self.unavailable("ground_truth_missing")
        sources = [span for span in context.trace.spans if span.op_type == "SOURCE" and span.status == "FIRED"]
        hits = {span.op_id: context.relevant_document_ids & {c.doc_id for c in span.outputs} for span in sources}
        hit_branches = {op_id: docs for op_id, docs in hits.items() if docs}
        missed_branches = tuple(op_id for op_id, docs in hits.items() if not docs)
        if hit_branches and missed_branches:
            documents = {doc for docs in hit_branches.values() for doc in docs}
            return finding(self, FindingAvailability.SUPPORTED, documents=documents, operators=(*hit_branches, *missed_branches), details={"hit_branches": list(hit_branches), "missed_branches": list(missed_branches)})
        return self.not_observed()


class GateExclusionRule(RuleBase):
    label = "gate_exclusion"

    def evaluate(self, context: DiagnosticContext):
        self.bind(context)
        if not context.relevant_document_ids:
            return self.unavailable("ground_truth_missing")
        skipped = [span for span in context.trace.spans if span.status == "SKIPPED_BY_GATE"]
        if not skipped:
            return self.not_observed()
        measured = [span for span in skipped if span.outputs]
        if not measured:
            return finding(self, FindingAvailability.LIMITED, operators=(s.op_id for s in skipped), limitations=("skipped_branch_counterfactual_not_captured",))
        excluded = {c.doc_id for span in measured for c in span.outputs} & context.relevant_document_ids
        return finding(self, FindingAvailability.SUPPORTED, documents=excluded, operators=(s.op_id for s in measured), details={"selected_route": context.trace.metadata.get("selected_route")}) if excluded else self.not_observed()
