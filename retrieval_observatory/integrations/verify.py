from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = ".retobs/results.db"
DEFAULT_SERVE_PORT = 4000


def dashboard_base_url() -> str:
    port = int(os.environ.get("RETOBS_SERVE_PORT", DEFAULT_SERVE_PORT))
    host = os.environ.get("RETOBS_SERVE_HOST", "127.0.0.1")
    return f"http://{host}:{port}"


def dashboard_run_url(run_id: str, section: str = "overview") -> str:
    return f"{dashboard_base_url()}/#/benchmarks/run/{run_id}/{section}"


def _store(db_path: str):
    from retrieval_observatory.store.sqlite import SQLiteStore

    return SQLiteStore(db_path=db_path)


async def verify_integration(
    db_path: str = DEFAULT_DB_PATH,
    run_id: Optional[str] = None,
    expected_stages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Report whether traces/metrics exist and suggest next MCP steps."""
    store = _store(db_path)
    await store.init_db()
    runs = await store.list_runs()
    if not runs:
        return {
            "status": "no_runs",
            "message": "No runs in database yet.",
            "next": "benchmark_config or push_traces, then call verify_integration again.",
            "dashboard_url": dashboard_base_url(),
        }

    target = run_id or runs[0]["run_id"]
    traces = await store.get_traces_v2(target) if hasattr(store, "get_traces_v2") else []
    from retrieval_observatory.metrics.engine import MetricsEngine

    metrics = await MetricsEngine().aggregate(target, store)
    stages_seen = sorted({span.op_id for trace in traces for span in trace.spans})
    pipeline_ids = sorted({v["pipeline_id"] for v in metrics.values() if v.get("stage_index", -1) >= 0})

    missing_stages: List[str] = []
    if expected_stages:
        missing_stages = sorted(set(expected_stages) - set(stages_seen))

    next_steps = ["get_run_metrics"]
    if pipeline_ids:
        next_steps.append("get_pareto_frontier")
        next_steps.append("get_pipeline_graph")
    if not traces:
        next_steps.insert(0, "describe_integration(framework='...') to wire tracing")
        next_steps.insert(1, "push_traces after instrumenting your pipeline")
    elif missing_stages:
        next_steps.insert(0, f"wire missing stages: {missing_stages}")

    instrumentation = "trace_native" if traces else "benchmark_only"
    if missing_stages:
        instrumentation = "incomplete"

    return {
        "status": "ok",
        "run_id": target,
        "trace_count": len(traces),
        "stages_seen": stages_seen,
        "missing_stages": missing_stages,
        "pipeline_ids": pipeline_ids,
        "has_metrics": bool(metrics),
        "instrumentation": instrumentation,
        "dashboard_url": dashboard_run_url(target),
        "next": next_steps,
    }
