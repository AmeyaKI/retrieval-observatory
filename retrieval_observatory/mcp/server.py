from __future__ import annotations

import functools
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import yaml

# MCP server exposing retobs to agents. Tool logic lives in plain async functions (importable and
# unit-testable without the `mcp` package); build_server() wraps them as FastMCP tools. Each tool
# is a thin adapter over the same SDK seam (run_from_config) and store/metric readers the REST
# layer uses, so an agent can "benchmark this config against a baseline" and read results back.
#
# Runs default to BOUNDED-SYNCHRONOUS with a small max_queries cap so a tool call returns within
# an agent's tool timeout. Large runs should go through the REST job model (POST /dbs/{id}/runs).

DEFAULT_DB_PATH = ".retobs/results.db"
DEFAULT_MAX_QUERIES = 50

from retrieval_observatory.integrations.verify import verify_integration


class _FallbackFastMCP:
    """Minimal stand-in used when the optional `mcp` package is not installed."""

    def __init__(self, name: str):
        self.name = name
        self._tools: List[tuple[str, Any]] = []

    def tool(self, name: Optional[str] = None):
        def decorator(func):
            self._tools.append((name or func.__name__, func))
            return func

        return decorator

    async def list_tools(self):
        return [SimpleNamespace(name=name) for name, _ in self._tools]

    def run(self) -> None:
        raise RuntimeError("The 'mcp' package is required to run the server. Install with: pip install 'retrieval-observatory[mcp]'")


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load simple MCP defaults from a YAML file if present."""
    if not config_path:
        candidate = Path("retobs-mcp.yaml")
        if candidate.exists():
            config_path = str(candidate)
        else:
            return {
                "db_path": DEFAULT_DB_PATH,
                "max_queries": DEFAULT_MAX_QUERIES,
                "baseline_run_id": None,
            }

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"MCP config not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return {
        "db_path": data.get("db_path", DEFAULT_DB_PATH),
        "max_queries": int(data.get("max_queries", DEFAULT_MAX_QUERIES)),
        "baseline_run_id": data.get("baseline_run_id"),
    }


def _with_config_defaults(config_path: Optional[str], func):
    """Wrap a tool so ``db_path``/``max_queries`` default to the MCP config file's values.

    The wrapper keeps the tool's real signature (with the config-derived defaults substituted):
    FastMCP derives each tool's input schema from ``inspect.signature``, and a bare
    ``(*args, **kwargs)`` wrapper used to publish ``args``/``kwargs`` as the only parameters,
    which made every wrapped tool uncallable by name.
    """
    cfg = load_config(config_path)
    # eval_str: FastMCP reads ``__signature__`` verbatim, so string annotations (this module uses
    # ``from __future__ import annotations``) must already be resolved to real types here.
    signature = inspect.signature(func, eval_str=True)
    overrides: Dict[str, Any] = {}
    if "db_path" in signature.parameters:
        overrides["db_path"] = cfg.get("db_path", DEFAULT_DB_PATH)
    if "max_queries" in signature.parameters:
        overrides["max_queries"] = int(cfg.get("max_queries", DEFAULT_MAX_QUERIES))

    def fill(args, kwargs):
        bound = signature.bind_partial(*args, **kwargs).arguments
        for name, value in overrides.items():
            if name not in bound:
                kwargs[name] = value
        return kwargs

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            return await func(*args, **fill(args, kwargs))
    else:
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            return func(*args, **fill(args, kwargs))

    wrapped.__signature__ = signature.replace(
        parameters=[
            parameter.replace(default=overrides[parameter.name]) if parameter.name in overrides else parameter
            for parameter in signature.parameters.values()
        ]
    )
    return wrapped


def _store(db_path: str):
    from retrieval_observatory.store.sqlite import SQLiteStore

    return SQLiteStore(db_path=db_path)


def _describe_config() -> Dict[str, Any]:
    """Return the ExperimentConfig JSON schema, a runnable example, per-adapter stage snippets,
    and notes. Call this FIRST to learn how to shape a config for benchmark_config /
    benchmark_vs_baseline — no external docs needed."""
    from retrieval_observatory.config.discovery import config_schema

    return config_schema()


def _validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Dry-run validate a config WITHOUT running a benchmark. Returns {valid, status, items};
    call this before benchmark_config to self-correct instead of failing a real run."""
    from retrieval_observatory.config.discovery import validate_config_dict

    return validate_config_dict(config)


async def _get_report(
    run_id: str,
    format: str = "json",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any] | str:
    """Render a run through the same report model as CLI and SDK."""
    from retrieval_observatory.sdk.report import load_run_report

    report = await load_run_report(run_id, db_path)
    if format == "json":
        return report.to_dict()
    if format == "audit":
        return report.audit or {}
    if format in {"markdown", "md", "terminal"}:
        return report.to_markdown()
    if format == "html":
        return report.to_html()
    raise ValueError("format must be json, audit, markdown, or html")


async def _compare_runs(
    baseline_run_id: str,
    candidate_run_id: str,
    format: str = "json",
    db_path: str = DEFAULT_DB_PATH,
    policy_path: Optional[str] = None,
) -> Dict[str, Any] | str:
    """Release comparison using an optional explicit local policy path; ``format="audit"`` returns the release audit."""
    from retrieval_observatory.sdk.report import load_comparison_report

    report = await load_comparison_report(
        baseline_run_id,
        candidate_run_id,
        db_path,
        policy=policy_path,
    )
    if format == "json":
        return report.to_dict()
    if format == "audit":
        return report.audit or {}
    if format in {"markdown", "md", "terminal"}:
        return report.to_markdown()
    if format == "html":
        return report.to_html()
    raise ValueError("format must be json, audit, markdown, or html")


async def _inspect_query(
    run_id: str,
    query_id: str,
    db_path: str = DEFAULT_DB_PATH,
    trace_limit: int = 20,
    trace_offset: int = 0,
) -> Dict[str, Any]:
    """Return the canonical scoped QueryEvidence document."""
    from retrieval_observatory.evidence import build_query_evidence

    store = _store(db_path)
    await store.init_db()
    return await build_query_evidence(
        store,
        db_id=Path(db_path).stem,
        run_id=run_id,
        query_id=query_id,
        trace_limit=min(max(trace_limit, 1), 100),
        trace_offset=max(trace_offset, 0),
    )


async def _inspect_document(
    run_id: str,
    entity: str,
    db_path: str = DEFAULT_DB_PATH,
    pipeline_id: Optional[str] = None,
    k: Optional[int] = None,
    unit: str = "document",
) -> Dict[str, Any]:
    """Return one evaluation entity's journey rows across every query of a run (``entity`` is ``namespace:id`` or a bare id)."""
    from retrieval_observatory.evidence import InvestigationError, InvestigationRequest, inspect_document

    store = _store(db_path)
    await store.init_db()
    request = {"run_id": run_id, "entity": entity, "pipeline_id": pipeline_id, "k": k, "unit": unit}
    try:
        return await inspect_document(store, InvestigationRequest.from_mapping(request))
    except InvestigationError as error:
        raise ValueError(f"{error.code}: {error.detail}") from error


async def _describe_integration(framework: Optional[str] = None) -> Dict[str, Any]:
    from retrieval_observatory.integrations.registry import describe_integration

    return describe_integration(framework)


async def _verify_integration(
    db_path: str = DEFAULT_DB_PATH,
    run_id: Optional[str] = None,
    expected_stages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Report whether traces/metrics exist and suggest next MCP steps."""
    return await verify_integration(db_path=db_path, run_id=run_id, expected_stages=expected_stages)


async def _integrate_project(
    project_root: str,
    phase: str = "plan",
    plan: Optional[Dict[str, Any]] = None,
    plan_path: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
    framework: Optional[str] = None,
) -> Dict[str, Any]:
    """Plan, apply, verify, or revert one project integration (phase = plan | apply | verify | revert).

    plan: discover operators and the entrypoint; save the result as retobs/integration-plan.json.
    plan with plan/plan_path: re-plan from your reviewed operators/scenarios; patches are regenerated
    (set an operator's capture to "retobs_adapter:<symbol>" to wire a CaptureSpec from retobs_adapter.py).
    apply: pass the reviewed plan (or plan_path); patches files and writes retobs/integration.yaml.
    verify: reads retobs/integration.yaml and the traces in db_path (relative paths resolve
    against project_root); plan/plan_path are optional here and must match the applied plan.
    revert: restores every file apply patched (refuses if one changed since) and removes
    retobs/integration.yaml; retobs/integration-plan.json is kept.
    framework: override detection (python, fastapi, langchain, llamaindex, http)."""
    from pathlib import Path
    from retrieval_observatory.integrations.model import IntegrationOptions, IntegrationPhase, IntegrationPlan
    from retrieval_observatory.integrations.service import integrate_project

    if plan and plan_path:
        raise ValueError("provide either plan or plan_path, not both")
    if plan_path:
        payload = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        plan = payload.get("plan", payload)
    reviewed = IntegrationPlan.from_dict(plan) if plan else None
    options = IntegrationOptions(reviewed, db_path, framework=framework)
    return (await integrate_project(Path(project_root), IntegrationPhase(phase), options)).to_dict()


async def _benchmark_config(
    config: Dict[str, Any],
    max_queries: int = DEFAULT_MAX_QUERIES,
    db_path: str = DEFAULT_DB_PATH,
    config_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Benchmark a retrieval config (ExperimentConfig JSON of adapter specs). Bounded-synchronous:
    capped at max_queries. Returns run_id, aggregated metrics, and the headline winner.
    Pass config_base_dir to resolve relative dataset paths and adapter.import factories."""
    from retrieval_observatory.dashboard.api import _headline_winner
    from retrieval_observatory.sdk.run_config import _run_from_config_async

    if max_queries < 1:
        raise ValueError(f"max_queries must be at least 1 (got {max_queries})")
    report = await _run_from_config_async(
        config=config,
        db_path=db_path,
        max_queries=max_queries,
        run_id=None,
        no_cache=False,
        config_base_dir=config_base_dir,
    )
    return {
        "run_id": report.run_id,
        "metrics": report.metrics,
        "headline_winner": _headline_winner(report.metrics),
    }


async def _benchmark_config_file(
    config_path: str,
    max_queries: int = DEFAULT_MAX_QUERIES,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Benchmark a YAML config file on disk with CLI-equivalent path resolution and sys.path setup."""
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    return await _benchmark_config(
        config,
        max_queries=max_queries,
        db_path=db_path,
        config_base_dir=str(path.parent),
    )


async def _get_pipeline_graph(
    run_id: str,
    db_path: str = DEFAULT_DB_PATH,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Canonical PipelineGraph projection (nodes + edges with CIs) from traces + metrics."""
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs

    store = _store(db_path)
    await store.init_db()
    agg = await MetricsEngine().aggregate(run_id, store)
    traces = await store.get_traces(run_id) if hasattr(store, "get_traces") else []
    graphs = build_pipeline_graphs(
        agg,
        traces,
        projection_mode="trace" if trace_id else "run_union",
        trace_id=trace_id,
    )
    return {
        "run_id": run_id,
        "pipelines": [g.to_dict() for g in graphs],
    }


def _parse_trace_payload(payload: Dict[str, Any], run_id: str):
    from retrieval_observatory.tracing.model import RetrievalTrace

    data = dict(payload)
    if run_id:
        data["run_id"] = run_id
    return RetrievalTrace.from_dict(data)


async def _push_traces(
    run_id: str,
    traces: List[Dict[str, Any]],
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Ingest V2 retrieval traces into a benchmark run (same contract as REST POST .../traces)."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    parsed = []
    for index, payload in enumerate(traces):
        if not isinstance(payload, dict):
            raise ValueError(f"trace[{index}] must be a JSON object (RetrievalTrace.to_dict() shape)")
        try:
            parsed.append(_parse_trace_payload(payload, run_id=run_id))
        except KeyError as error:
            raise ValueError(f"trace[{index}] missing field {error.args[0]!r}") from error
        except (TypeError, ValueError) as error:
            raise ValueError(f"trace[{index}] is not a valid RetrievalTrace: {error}") from error
    store = _store(db_path)
    await store.init_db()
    stored: List[str] = []
    for trace in parsed:
        await store.save_trace(trace)
        stored.append(trace.trace_id)
    return {"run_id": run_id, "trace_ids": stored, "count": len(stored)}


def _mcp_server_cls():
    """Resolve the installed MCP server class (1.x FastMCP or 2.x MCPServer)."""
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError:
        pass
    try:
        # mcp>=2 removed FastMCP; MCPServer is the compatible replacement.
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:  # pragma: no cover - exercised only without the extra
        return _FallbackFastMCP


def build_server(config_path: Optional[str] = None):
    """Construct the FastMCP/MCPServer with all retobs tools registered."""
    server = _mcp_server_cls()("retrieval-observatory")
    # Task-oriented public tools. These nouns and result contracts match CLI/SDK/UI.
    server.tool(name="evaluate")(_with_config_defaults(config_path, _benchmark_config))
    server.tool(name="evaluate_file")(_with_config_defaults(config_path, _benchmark_config_file))
    server.tool(name="compare")(_with_config_defaults(config_path, _compare_runs))
    server.tool(name="inspect_query")(_with_config_defaults(config_path, _inspect_query))
    server.tool(name="inspect_document")(_with_config_defaults(config_path, _inspect_document))
    server.tool(name="get_report")(_with_config_defaults(config_path, _get_report))
    server.tool(name="describe_config")(_describe_config)
    server.tool(name="validate_config")(_validate_config)
    server.tool(name="integrate_project")(_with_config_defaults(config_path, _integrate_project))
    server.tool(name="verify_integration")(_with_config_defaults(config_path, _verify_integration))
    server.tool(name="push_traces")(_with_config_defaults(config_path, _push_traces))
    server.tool(name="get_pipeline_graph")(_with_config_defaults(config_path, _get_pipeline_graph))
    return server


def main(config_path: Optional[str] = None) -> None:
    """Entry point for `retobs mcp` — run the server over stdio."""
    build_server(config_path).run()


if __name__ == "__main__":
    main()
