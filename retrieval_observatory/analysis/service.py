from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from retrieval_observatory.analysis.cohorts import CohortClause, CohortDefinition, matches_cohort
from retrieval_observatory.analysis.contracts import AnalysisScope


def cohort_from_record(record: Mapping[str, Any]) -> CohortDefinition:
    return CohortDefinition(
        str(record["cohort_id"]),
        str(record["name"]),
        int(record["version"]),
        tuple(CohortClause(**clause) for clause in record["clauses"]),
        str(record.get("conjunction", "all")),  # type: ignore[arg-type]
    )


def trace_record(trace: Any) -> dict[str, Any]:
    return {
        "query": {"id": trace.query_id, "text": trace.query_text, "metadata": trace.metadata.get("query_metadata", {})},
        "trace": {
            "status": trace.status,
            "service": trace.service_id,
            "pipeline_id": trace.pipeline_id,
            "topology_id": trace.topology_hash,
            "total_latency_ms": trace.timing.wall_clock_ms if trace.timing else None,
            "metadata": trace.metadata,
        },
        "route": {
            "value": next((span.gate_values.get("route") for span in trace.spans if span.op_type == "GATE"), None)
        },
    }


def filter_traces(traces: Sequence[Any], cohort: CohortDefinition | None) -> list[Any]:
    return (
        list(traces) if cohort is None else [trace for trace in traces if matches_cohort(trace_record(trace), cohort)]
    )


def make_scope(
    db_id: str,
    service_id: str | None,
    run_id: str | None,
    since: datetime | None,
    until: datetime | None,
    cohort_id: str | None,
) -> AnalysisScope:
    return AnalysisScope(db_id, service_id, run_id, since, until, cohort_id)
