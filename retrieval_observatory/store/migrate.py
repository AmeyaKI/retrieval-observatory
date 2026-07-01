"""Migration helpers for retiring PipelineResult persistence (Phase 9).

Provides ``migrate_run_to_v2()`` to convert old ``raw_results``/snapshot data
into ``traces_v2`` entries, enabling the eventual deprecation of
``save_result()`` and ``get_results()``.
"""
from __future__ import annotations

from typing import List

from retrieval_observatory.store.base import BaseStore
from retrieval_observatory.tracing.lift import lift_pipeline_result
from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2


async def migrate_run_to_v2(
    run_id: str,
    store: BaseStore,
    *,
    overwrite: bool = False,
) -> int:
    """Lift all PipelineResults for *run_id* into traces_v2.

    Returns the number of traces written. If *overwrite* is False (default),
    skips traces whose trace_id already exists in traces_v2.
    """
    results = await store.get_results(run_id)
    if not results:
        return 0

    existing_ids: set[str] = set()
    if not overwrite:
        existing = await store.get_traces_v2(run_id)
        existing_ids = {t.trace_id for t in existing}

    written = 0
    for result in results:
        trace = lift_pipeline_result(result, run_id=run_id)
        if not overwrite and trace.trace_id in existing_ids:
            continue
        await store.save_trace_v2(trace)
        written += 1
    return written


async def verify_migration_parity(
    run_id: str,
    store: BaseStore,
) -> dict:
    """Compare legacy results with migrated V2 traces.

    Returns a dict with parity status and any mismatches.
    """
    results = await store.get_results(run_id)
    traces = await store.get_traces_v2(run_id)

    result_keys = {(r.query_id, r.pipeline_id) for r in results}
    trace_keys = {(t.query_id, t.pipeline_id) for t in traces}

    missing_traces = result_keys - trace_keys
    extra_traces = trace_keys - result_keys

    doc_mismatches: list[dict] = []
    for result in results:
        key = (result.query_id, result.pipeline_id)
        trace = next((t for t in traces if (t.query_id, t.pipeline_id) == key), None)
        if trace is None or not result.snapshots or not trace.spans:
            continue
        legacy_docs = [d.id for d in result.snapshots[-1].documents]
        final_span = None
        if trace.final_op_id:
            final_span = next((s for s in trace.spans if s.op_id == trace.final_op_id), None)
        if final_span is None and trace.spans:
            final_span = trace.spans[-1]
        trace_docs = [c.doc_id for c in final_span.outputs] if final_span else []
        if legacy_docs != trace_docs:
            doc_mismatches.append({
                "query_id": result.query_id,
                "pipeline_id": result.pipeline_id,
                "legacy_count": len(legacy_docs),
                "trace_count": len(trace_docs),
            })

    return {
        "parity": len(missing_traces) == 0 and len(doc_mismatches) == 0,
        "result_count": len(results),
        "trace_count": len(traces),
        "missing_traces": [{"query_id": q, "pipeline_id": p} for q, p in missing_traces],
        "extra_traces": [{"query_id": q, "pipeline_id": p} for q, p in extra_traces],
        "doc_mismatches": doc_mismatches,
    }
