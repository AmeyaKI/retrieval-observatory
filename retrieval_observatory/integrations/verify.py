from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = ".retobs/results.db"
DEFAULT_SERVE_PORT = 4000

# The operator vocabulary the platform understands (mirrors model_v2.OperatorType).
_KNOWN_OP_TYPES = {"SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE", "TRANSFORM", "GENERATE"}


def _integration_checks(traces: list) -> List[Dict[str, Any]]:
    """The Integration Verification checklist from the vision doc's Pillar 4 — run against
    persisted traces so problems surface before the user trusts a benchmark.

    Each check: {name, status: 'ok'|'warn'|'error', detail}.
    """
    checks: List[Dict[str, Any]] = []
    n = len(traces)

    if n == 0:
        checks.append({"name": "traces_present", "status": "error",
                       "detail": "No V2 traces found — instrumentation is not delivering traces."})
        return checks
    checks.append({"name": "traces_present", "status": "ok", "detail": f"{n} traces recorded."})

    # Metadata completeness: query text + candidate scores should be present to debug.
    missing_query_text = sum(1 for t in traces if not getattr(t, "query_text", ""))
    if missing_query_text:
        checks.append({"name": "query_text_metadata", "status": "warn",
                       "detail": f"{missing_query_text}/{n} traces have no query_text — query-centric views degrade."})
    else:
        checks.append({"name": "query_text_metadata", "status": "ok", "detail": "All traces carry query text."})

    spans = [s for t in traces for s in t.spans]
    missing_scores = sum(1 for s in spans for c in s.outputs if c.score is None)
    if missing_scores:
        checks.append({"name": "candidate_scores", "status": "warn",
                       "detail": f"{missing_scores} output candidates have no score — attribution/flow degrade."})
    else:
        checks.append({"name": "candidate_scores", "status": "ok", "detail": "All candidates carry scores."})

    # Unsupported-operator detection.
    unknown_ops = sorted({str(s.op_type) for s in spans if str(s.op_type) not in _KNOWN_OP_TYPES})
    if unknown_ops:
        checks.append({"name": "supported_operators", "status": "error",
                       "detail": f"Unsupported operator types: {unknown_ops}. Map them to a known OperatorType."})
    else:
        checks.append({"name": "supported_operators", "status": "ok", "detail": "All operator types are supported."})

    # Error / timeout rate.
    bad = sum(1 for t in traces if getattr(t, "status", "OK") in ("ERROR", "TIMEOUT"))
    if bad:
        checks.append({"name": "trace_health", "status": "warn",
                       "detail": f"{bad}/{n} traces ended in ERROR/TIMEOUT."})
    else:
        checks.append({"name": "trace_health", "status": "ok", "detail": "No error/timeout traces."})

    # Sampling signal: if traces advertise a sampling rate in metadata, surface it.
    rates = {t.metadata.get("sampling_rate") for t in traces if getattr(t, "metadata", None) and "sampling_rate" in t.metadata}
    rates.discard(None)
    if rates and any(r < 1.0 for r in rates if isinstance(r, (int, float))):
        checks.append({"name": "sampling_rate", "status": "warn",
                       "detail": f"Traces are sampled (rates={sorted(rates)}); metrics reflect a subset of traffic."})

    return checks


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

    checks = _integration_checks(traces)
    if missing_stages:
        checks.append({"name": "expected_stages", "status": "warn",
                       "detail": f"Configured stages not observed in traces: {missing_stages}."})
    check_status = "error" if any(c["status"] == "error" for c in checks) else (
        "warn" if any(c["status"] == "warn" for c in checks) else "ok")

    return {
        "status": "ok",
        "run_id": target,
        "trace_count": len(traces),
        "stages_seen": stages_seen,
        "missing_stages": missing_stages,
        "pipeline_ids": pipeline_ids,
        "has_metrics": bool(metrics),
        "instrumentation": instrumentation,
        "checks": checks,
        "check_status": check_status,
        "dashboard_url": dashboard_run_url(target),
        "next": next_steps,
    }
