from typing import Any, Mapping, Sequence
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_ground_truth(
    qrels: Mapping[str, Mapping[str, int]],
    queries: Sequence[Mapping[str, Any]],
    judgments: Sequence[Mapping[str, Any]],
    scope: AnalysisScope,
):
    effective = {query_id: dict(labels) for query_id, labels in qrels.items()}
    for judgment in judgments:
        if judgment.get("query_id") and judgment.get("doc_id") and judgment.get("label") is not None:
            effective.setdefault(str(judgment["query_id"]), {})[str(judgment["doc_id"])] = int(judgment["label"])
    if not effective:
        return unavailable(scope, "ground_truth", "No qrels or judgments were available.")
    query_ids = {str(value) for q in queries if (value := q.get("query_id") or q.get("id"))}
    labeled = set(effective)
    population = query_ids | labeled
    conflicts = sum(1 for j in judgments if j.get("supersedes") and j.get("label") != j.get("previous_label"))
    data = {
        "query_count": len(query_ids),
        "labeled_count": len(labeled),
        "coverage": len(labeled & query_ids) / max(1, len(query_ids)),
        "orphan_query_ids": sorted(labeled - query_ids),
        "judgment_count": len(judgments),
        "conflict_count": conflicts,
        "audit_queue": [q for q in sorted(query_ids) if q not in labeled],
    }
    limitations = tuple(
        message
        for message, present in (
            ("Some queries lack labels and are queued for audit.", bool(query_ids - labeled)),
            ("Some labels reference queries outside the scoped query set.", bool(labeled - query_ids)),
        )
        if present
    )
    return result(
        scope,
        "ground_truth",
        data,
        len(labeled & query_ids),
        len(population),
        evidence_class="measured",
        limitations=limitations,
    )
