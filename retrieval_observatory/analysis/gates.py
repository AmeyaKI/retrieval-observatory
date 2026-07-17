from collections import Counter
from typing import Any, Mapping, Sequence
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_gates(
    traces: Sequence[Any], qrels: Mapping[str, Any], route_labels: Mapping[str, str], scope: AnalysisScope
):
    spans = [s for t in traces for s in t.spans if s.op_type == "GATE"]
    if not spans:
        return unavailable(scope, "gates", "No GATE operator spans were captured in this scope.")
    routes = Counter(str(s.gate_values.get("route", s.status)) for s in spans)
    quality: dict[str, list[float]] = {}
    for trace in traces:
        relevant = set(qrels.get(trace.query_id, {}))
        terminal = next((span for span in trace.spans if span.op_id in trace.final_op_ids), None)
        route = next(
            (str(span.gate_values.get("route", span.status)) for span in trace.spans if span.op_type == "GATE"), None
        )
        if route and relevant and terminal:
            quality.setdefault(route, []).append(
                len(relevant & {item.doc_id for item in terminal.outputs}) / len(relevant)
            )
    data = {
        "traffic": dict(routes),
        "decisions": dict(Counter(s.status for s in spans)),
        "route_quality": {
            route: {"recall": sum(values) / len(values), "sample_size": len(values)}
            for route, values in quality.items()
        },
        "confusion": None,
    }
    limitations = ()
    if route_labels:
        confusion = {}
        for t in traces:
            expected = route_labels.get(t.query_id)
            for s in t.spans:
                if s.op_type == "GATE" and expected:
                    actual = str(s.gate_values.get("route", s.status))
                    confusion.setdefault(expected, Counter())[actual] += 1
        data["confusion"] = {k: dict(v) for k, v in confusion.items()}
    else:
        limitations = ("Explicit route labels are unavailable; confusion is not computed.",)
    return result(
        scope,
        "gates",
        data,
        len(spans),
        len(spans) + int(bool(limitations)),
        limitations=limitations,
        trace_ids=tuple(t.trace_id for t in traces),
    )
