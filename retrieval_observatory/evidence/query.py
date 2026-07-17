from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from retrieval_observatory.store.base import TraceQuery


async def build_query_evidence(
    store: Any,
    *,
    db_id: str,
    run_id: str,
    query_id: str,
    trace_limit: int = 20,
    trace_offset: int = 0,
    candidate_limit: int = 100,
) -> Dict[str, Any]:
    """Build one database- and run-scoped query evidence document."""
    run_rows = [run for run in await store.list_runs() if run.get("run_id") == run_id]
    if not run_rows:
        raise LookupError(f"Run '{run_id}' not found")
    run_queries = await store.get_run_queries(run_id)
    query_row = next((row for row in run_queries if row.get("query_id") == query_id), None)
    stored_findings = await store.query_diagnostics(run_id, query_id=query_id)
    diagnostics = [finding.to_dict() for finding in stored_findings]
    qrels = await store.get_qrels(run_id)
    trace_page = await store.list_traces(
        TraceQuery(run_id=run_id, query_id=query_id, limit=trace_limit + 1, offset=trace_offset)
    )
    has_more = len(trace_page) > trace_limit
    traces = trace_page[:trace_limit]
    lineage = await store.get_query_lineage(query_id)

    from retrieval_observatory.advisor.recommend import recommend

    findings = [asdict(finding) for finding in await recommend(run_id, store)]
    diagnostic_labels = {
        label
        for diagnostic in diagnostics
        for label in ([diagnostic["label"]] if diagnostic.get("availability") == "supported" else [])
    }
    relevant_findings = [
        finding
        for finding in findings
        if not finding.get("affected_query_categories")
        or diagnostic_labels.intersection(finding.get("affected_query_categories") or [])
    ]

    serialized_traces = [
        _serialize_trace(trace.to_dict(), candidate_limit=candidate_limit)
        for trace in traces
    ]
    relevant_ids = sorted(
        doc_id
        for doc_id, grade in (qrels.get(query_id) or {}).items()
        if int(grade) > 0
    )
    warnings = []
    if query_row is None:
        warnings.append("Query text metadata is unavailable for this run.")
    if not relevant_ids:
        warnings.append("No positive relevance judgments are available for this query.")
    if not traces:
        warnings.append("No operator traces are available for this query.")
    partial_count = sum(trace.status != "OK" for trace in traces)
    if partial_count:
        warnings.append(f"{partial_count} returned trace(s) are partial or failed.")

    return {
        "schema_version": 1,
        "scope": {"db_id": db_id, "run_id": run_id, "query_id": query_id},
        "query": {
            "query_id": query_id,
            "text": (query_row or {}).get("query_text"),
            "dataset_name": (query_row or {}).get("dataset_name"),
        },
        "ground_truth": {
            "relevant_doc_ids": relevant_ids,
            "grades": qrels.get(query_id) or {},
            "evidence_class": "measured" if relevant_ids else "unavailable",
        },
        "diagnostics": diagnostics,
        "traces": serialized_traces,
        "trace_pagination": {
            "limit": trace_limit,
            "offset": trace_offset,
            "returned": len(traces),
            "has_more": has_more,
            "next_offset": trace_offset + len(traces) if has_more else None,
        },
        "origin": lineage.get("origin"),
        "regression_history": lineage.get("evaluations", []),
        "production_matches": lineage.get("production_matches"),
        "findings": relevant_findings,
        "availability": {
            "query_metadata": "measured" if query_row else "unavailable",
            "ground_truth": "measured" if relevant_ids else "unavailable",
            "operator_traces": "measured" if traces else "unavailable",
            "diagnostics": "measured" if diagnostics else "unavailable",
            "production_matches": (
                "measured"
                if (lineage.get("production_matches") or {}).get("traces")
                else "unavailable"
            ),
            "findings": "heuristic" if relevant_findings else "unavailable",
        },
        "evidence_health": {
            "status": "warning" if warnings else "ok",
            "complete_trace_count": sum(trace.status == "OK" for trace in traces),
            "partial_trace_count": partial_count,
            "warnings": warnings,
        },
    }


def _serialize_trace(trace: Dict[str, Any], *, candidate_limit: int) -> Dict[str, Any]:
    for span in trace.get("spans", []):
        fields = {"outputs": span.get("outputs", [])}
        fields.update(span.get("input_groups", {}))
        for field, candidates in fields.items():
            span[f"{field}_total"] = len(candidates)
            span[f"{field}_truncated"] = len(candidates) > candidate_limit
            if field == "outputs":
                span[field] = candidates[:candidate_limit]
            else:
                span.setdefault("input_groups", {})[field] = candidates[:candidate_limit]
    return trace
