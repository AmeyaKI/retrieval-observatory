from typing import Any, Mapping, Sequence
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_scores(traces: Sequence[Any], qrels: Mapping[str, Mapping[str, int]], scope: AnalysisScope, bins: int = 10):
    rows = [
        (float(c.score), c.doc_id in qrels.get(t.query_id, {}), s.op_id, t.query_id)
        for t in traces
        for s in t.spans
        for c in s.outputs
        if c.score is not None
    ]
    if not rows:
        return unavailable(scope, "scores", "No scored candidates were captured.")
    labeled = [row for row in rows if row[3] in qrels]
    if not labeled:
        return unavailable(scope, "scores", "Calibration requires explicit relevance labels.")
    by_op = {}
    for score, relevant, op, _ in labeled:
        by_op.setdefault(op, []).append((score, relevant))

    def summarize(values):
        ordered = sorted(values)
        low, high = ordered[0][0], ordered[-1][0]
        width = (high - low) / max(1, bins)
        calibration = []
        for index in range(1 if width == 0 else bins):
            start = low + index * width
            end = high if index == bins - 1 else start + width
            members = [value for value in ordered if start <= value[0] <= end]
            if members:
                calibration.append(
                    {
                        "score_low": start,
                        "score_high": end,
                        "count": len(members),
                        "relevance_rate": sum(item[1] for item in members) / len(members),
                    }
                )
        thresholds = []
        for threshold in sorted({value[0] for value in ordered}):
            selected = [value for value in ordered if value[0] >= threshold]
            thresholds.append(
                {
                    "threshold": threshold,
                    "selected": len(selected),
                    "precision": sum(item[1] for item in selected) / len(selected),
                }
            )
        return {
            "count": len(values),
            "score_min": low,
            "score_max": high,
            "positive_rate": sum(item[1] for item in values) / len(values),
            "calibration_bins": calibration,
            "threshold_sensitivity": thresholds,
        }

    data = {
        "operators": {op: summarize(values) for op, values in by_op.items()},
        "normalization": "within_operator_only",
    }
    limitations = tuple(
        item
        for item in (
            "Cross-operator score comparison is prohibited without recorded normalization." if len(by_op) > 1 else None,
            "Unlabeled candidates were excluded from calibration." if len(labeled) < len(rows) else None,
        )
        if item
    )
    return result(
        scope,
        "scores",
        data,
        len(labeled),
        len(rows) + int(bool(limitations) and len(labeled) == len(rows)),
        evidence_class="statistical",
        limitations=limitations,
    )
