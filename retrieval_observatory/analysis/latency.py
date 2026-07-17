from typing import Any, Sequence
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_latency(traces: Sequence[Any], scope: AnalysisScope):
    valid = [t for t in traces if t.timing is not None and t.spans]
    if not valid:
        return unavailable(scope, "latency", "No validated trace timing and operator spans were captured.")
    ops = {}
    paths = []
    components: dict[str, list[float]] = {}
    for t in valid:
        for s in t.spans:
            ops.setdefault(s.op_id, []).append(s.latency_ms)
            for name, value in s.params.get("timing_components", {}).items():
                if isinstance(value, (int, float)) and value >= 0:
                    components.setdefault(name, []).append(float(value))
        by_id = {span.op_id: span for span in t.spans}
        cache: dict[str, tuple[float, list[str]]] = {}

        def longest(op_id: str):
            if op_id not in cache:
                parent = max(
                    (longest(parent_id) for parent_id in by_id[op_id].parent_ids),
                    default=(0.0, []),
                    key=lambda item: item[0],
                )
                cache[op_id] = (parent[0] + by_id[op_id].latency_ms, [*parent[1], op_id])
            return cache[op_id]

        paths.append(max((longest(op_id) for op_id in by_id), key=lambda item: item[0]))
    data = {
        "wall_clock_ms": sum(t.timing.wall_clock_ms for t in valid) / len(valid),
        "critical_path_ms": sum(t.timing.critical_path_ms for t in valid) / len(valid),
        "operator_sum_ms": sum(t.timing.operator_sum_ms for t in valid) / len(valid),
        "operators": {k: sum(v) / len(v) for k, v in ops.items()},
        "critical_paths": [{"latency_ms": latency, "operator_ids": operator_ids} for latency, operator_ids in paths],
        "timing_components": {name: sum(values) / len(values) for name, values in components.items()} or None,
    }
    limitations = ("Some traces lacked validated timing and were excluded.",) if len(valid) < len(traces) else ()
    return result(scope, "latency", data, len(valid), len(traces), limitations=limitations)
