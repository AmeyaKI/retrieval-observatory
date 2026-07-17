from typing import Any, Mapping, Sequence
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_instrumentation(
    manifest: Any, traces: Sequence[Any], health: Mapping[str, Any] | Any | None, scope: AnalysisScope
):
    if manifest is None and health is None:
        return unavailable(
            scope, "instrumentation", "No integration manifest or capture-health snapshot was available."
        )
    if manifest is not None and health is None and not traces:
        return unavailable(
            scope, "instrumentation", "A manifest exists, but no traces or capture-health snapshot were observed."
        )
    h = health if isinstance(health, Mapping) else getattr(health, "__dict__", {})
    declared = {op.op_id for op in getattr(manifest, "operators", ())}
    observed = {s.op_id for t in traces for s in t.spans}
    accepted = int(h.get("accepted", 0))
    exported = int(h.get("exported", 0))
    dropped = int(h.get("dropped", 0))
    failures = int(h.get("serialization_failures", 0)) + int(h.get("permanent_failures", 0))
    data = {
        "declared_operator_ids": sorted(declared),
        "observed_operator_ids": sorted(observed),
        "missing_operator_ids": sorted(declared - observed),
        "accepted": accepted,
        "exported": exported,
        "dropped": dropped,
        "failures": failures,
        "delivery_rate": exported / max(1, accepted),
    }
    degraded = bool(declared - observed or dropped or failures)
    limitations = (
        ("Capture is degraded; missing operators or declared loss counters require remediation.",) if degraded else ()
    )
    return result(
        scope,
        "instrumentation",
        data,
        max(1, len(traces)),
        max(1, len(traces) + int(degraded)),
        limitations=limitations,
    )
