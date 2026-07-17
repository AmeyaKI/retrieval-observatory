from typing import Any, Mapping, Sequence
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_branches(traces: Sequence[Any], qrels: Mapping[str, Mapping[str, int]], scope: AnalysisScope):
    fusions = [(t, s) for t in traces for s in t.spans if s.op_type == "FUSE" and len(s.input_groups) > 1]
    if not fusions:
        return unavailable(scope, "branches", "No multi-branch fusion evidence with stable origins was captured.")
    rows = []
    inferred = False
    for trace, span in fusions:
        groups = {k: {c.doc_id for c in v} for k, v in span.input_groups.items()}
        names = list(groups)
        overlap = set.intersection(*(groups[n] for n in names)) if names else set()
        relevant = set(qrels.get(trace.query_id, {}))
        cutoff = len(span.outputs)
        branch_union = set().union(*(groups[name] for name in names))
        fused = {candidate.doc_id for candidate in span.outputs[:cutoff]}
        rows.append(
            {
                "op_id": span.op_id,
                "branches": {
                    n: {
                        "count": len(groups[n]),
                        "unique_relevant_count": len(
                            (groups[n] - set().union(*(groups[x] for x in names if x != n))) & relevant
                        ),
                    }
                    for n in names
                },
                "overlap_count": len(overlap),
                "relevant_union_at_cutoff": len(branch_union & relevant),
                "relevant_fused_at_cutoff": len(fused & relevant),
                "measured_fusion_gain": len(fused & relevant) - len(branch_union & relevant),
                "removal_evidence": "replayed" if span.replay_policy != "NOT_REPLAYABLE" else "inferred",
            }
        )
        inferred |= span.replay_policy == "NOT_REPLAYABLE"
    return result(
        scope,
        "branches",
        {"fusions": rows},
        len(fusions),
        len(fusions) + int(inferred),
        evidence_class="inferred" if inferred else "replayed",
        limitations=("Non-replayable branch removal estimates are observational.",) if inferred else (),
    )
