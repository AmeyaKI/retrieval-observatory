from __future__ import annotations

import inspect
import os
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
DEFAULT_SERVE_PORT = 4000


def _dashboard_base_url() -> str:
    port = int(os.environ.get("RETOBS_SERVE_PORT", DEFAULT_SERVE_PORT))
    host = os.environ.get("RETOBS_SERVE_HOST", "127.0.0.1")
    return f"http://{host}:{port}"


def _dashboard_run_url(run_id: str, section: str = "overview") -> str:
    return f"{_dashboard_base_url()}/#/benchmarks/run/{run_id}/{section}"


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
    cfg = load_config(config_path)
    params = inspect.signature(func).parameters

    if inspect.iscoroutinefunction(func):
        async def wrapped(*args, **kwargs):
            if "db_path" in params and "db_path" not in kwargs:
                kwargs["db_path"] = cfg.get("db_path", DEFAULT_DB_PATH)
            if "max_queries" in params and "max_queries" not in kwargs:
                kwargs["max_queries"] = int(cfg.get("max_queries", DEFAULT_MAX_QUERIES))
            return await func(*args, **kwargs)

        return wrapped

    def wrapped(*args, **kwargs):
        if "db_path" in params and "db_path" not in kwargs:
            kwargs["db_path"] = cfg.get("db_path", DEFAULT_DB_PATH)
        if "max_queries" in params and "max_queries" not in kwargs:
            kwargs["max_queries"] = int(cfg.get("max_queries", DEFAULT_MAX_QUERIES))
        return func(*args, **kwargs)

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


async def _list_runs(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """List benchmark runs stored in a retobs database."""
    store = _store(db_path)
    await store.init_db()
    runs = await store.list_runs()
    return [
        {
            "run_id": r.get("run_id"),
            "experiment_name": r.get("experiment_name"),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        }
        for r in runs
    ]


async def _get_run_metrics(run_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Aggregated metrics for a run: mean + bootstrap CI per pipeline/stage/metric."""
    from retrieval_observatory.metrics.engine import MetricsEngine

    store = _store(db_path)
    await store.init_db()
    return await MetricsEngine().aggregate(run_id, store)


def _normalize_benchmark_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Accept full ExperimentConfig or legacy pipeline-descriptor shape."""
    if config.get("experiment") and config.get("dataset"):
        return config
    if "pipelines" in config and ("dataset" in config or config.get("name")):
        name = str(config.get("name", config.get("experiment", {}).get("name", "mcp-pipeline")))
        return {
            "experiment": {"name": name},
            "dataset": config.get("dataset", {}),
            "pipelines": config.get("pipelines", []),
            "output": config.get("output", {"store": "sqlite", "db_path": DEFAULT_DB_PATH}),
            **{k: v for k, v in config.items() if k in ("metrics", "execution", "combinations", "stages", "costs", "graphs")},
        }
    raise ValueError(
        "Config must be an ExperimentConfig (experiment + dataset + pipelines) "
        "or a legacy descriptor with name, dataset, and pipelines."
    )


async def _describe_integration(framework: Optional[str] = None) -> Dict[str, Any]:
    from retrieval_observatory.integrations.registry import describe_integration

    return describe_integration(framework)


async def _verify_integration(
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
            "dashboard_url": _dashboard_base_url(),
        }

    target = run_id or runs[0]["run_id"]
    traces = await store.get_traces_v2(target) if hasattr(store, "get_traces_v2") else []
    from retrieval_observatory.metrics.engine import MetricsEngine

    metrics = await MetricsEngine().aggregate(target, store)
    stages_seen = sorted(
        {
            span.op_id
            for trace in traces
            for span in trace.spans
        }
    )
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
        "dashboard_url": _dashboard_run_url(target),
        "next": next_steps,
    }


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

    normalized = _normalize_benchmark_config(config)
    report = await _run_from_config_async(
        config=normalized,
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


async def _benchmark_pipeline_descriptor(
    descriptor: Dict[str, Any],
    max_queries: int = DEFAULT_MAX_QUERIES,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Deprecated — use benchmark_config with the same shape (auto-normalized)."""
    out = await _benchmark_config(descriptor, max_queries=max_queries, db_path=db_path)
    return {
        **out,
        "deprecated": "benchmark_pipeline_descriptor is deprecated; pass this shape to benchmark_config instead.",
    }


async def _benchmark_vs_baseline(
    candidate_config: Dict[str, Any],
    baseline_run_id: Optional[str] = None,
    baseline_config: Optional[Dict[str, Any]] = None,
    max_queries: int = DEFAULT_MAX_QUERIES,
    db_path: str = DEFAULT_DB_PATH,
    config_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Benchmark a candidate config against a baseline (an existing run_id OR another config).
    Returns candidate/baseline run ids and significance-tested regressions."""
    from retrieval_observatory.advisor.regression import detect_regressions
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.sdk.run_config import _run_from_config_async

    if not baseline_run_id and not baseline_config:
        raise ValueError("Provide either baseline_run_id or baseline_config.")

    store = _store(db_path)
    await store.init_db()

    if baseline_config is not None:
        baseline_report = await _run_from_config_async(
            config=baseline_config,
            db_path=db_path,
            max_queries=max_queries,
            run_id=None,
            no_cache=False,
            config_base_dir=config_base_dir,
        )
        baseline_run_id = baseline_report.run_id

    candidate_report = await _run_from_config_async(
        config=candidate_config,
        db_path=db_path,
        max_queries=max_queries,
        run_id=None,
        no_cache=False,
        config_base_dir=config_base_dir,
    )

    engine = MetricsEngine()
    findings = await detect_regressions(baseline_run_id, candidate_report.run_id, store, engine=engine)
    return {
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_report.run_id,
        "regressions": [
            {
                "metric": f.metric,
                "before": f.before,
                "after": f.after,
                "delta": f.delta,
                "q_value": f.q_value,
                "severity": f.severity,
            }
            for f in findings
        ],
        "significant": any(f.q_value < 0.05 for f in findings),
    }


async def _get_pareto_frontier(run_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Pareto-optimal pipelines for a run (quality vs latency)."""
    from retrieval_observatory.dashboard.api import _extract_final_stage_metrics
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.metrics.pareto import ParetoPipelineInput, compute_pareto_frontier

    store = _store(db_path)
    await store.init_db()
    agg = await MetricsEngine().aggregate(run_id, store)
    final = _extract_final_stage_metrics(agg)
    inputs = [
        ParetoPipelineInput(
            pipeline_id=pid,
            stage_index=m["stage_index"],
            ndcg10=m["ndcg10"],
            recall10=m["recall10"],
            latency_p50=m["latency_p50"],
            latency_p95=m["latency_p95"],
            ndcg10_ci_low=m.get("ndcg10_ci_low"),
            ndcg10_ci_high=m.get("ndcg10_ci_high"),
            recall10_ci_low=m.get("recall10_ci_low"),
            recall10_ci_high=m.get("recall10_ci_high"),
        )
        for pid, m in final.items()
    ]
    result = compute_pareto_frontier(inputs)
    return {
        "run_id": run_id,
        "objectives": result.objectives,
        "frontier_order": result.frontier_order,
        "pipelines": [
            {
                "pipeline_id": row.pipeline_id,
                "metrics": row.metrics,
                "is_pareto_optimal": row.is_pareto_optimal,
                "dominated_by": row.dominated_by,
            }
            for row in result.pipelines
        ],
    }


async def _get_recommendations(run_id: str, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Advisor recommendations for improving a run's retrieval pipeline."""
    from retrieval_observatory.advisor.recommend import recommend

    store = _store(db_path)
    await store.init_db()
    recs = await recommend(run_id, store)
    return [
        {"action": r.action, "rationale": r.rationale, "evidence": r.evidence, "priority": r.priority}
        for r in recs
    ]


async def _get_operator_attribution(
    run_id: str, metric: str = "recall", k: int = 10, db_path: str = DEFAULT_DB_PATH
) -> List[Dict[str, Any]]:
    """Per-operator marginal contribution (with CIs) via trace replay ablation."""
    from retrieval_observatory.tracing.attribution import operator_marginal_contribution

    store = _store(db_path)
    await store.init_db()
    traces = await store.get_traces_v2(run_id)
    qrels = await store.get_qrels(run_id) if hasattr(store, "get_qrels") else {}
    op_ids = sorted({span.op_id for trace in traces for span in trace.spans})
    out: List[Dict[str, Any]] = []
    for op_id in op_ids:
        for r in operator_marginal_contribution(traces, op_id=op_id, qrels=qrels, metric=metric, k=k):
            out.append(r.__dict__)
    return out


async def _get_pipeline_diagram(run_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Diagram-ready pipeline JSON: per-stage nodes with metrics + bootstrap CIs, and edges."""
    from retrieval_observatory.dashboard.api import _build_diagram, _pipeline_results_from_traces
    from retrieval_observatory.metrics.engine import MetricsEngine

    store = _store(db_path)
    await store.init_db()
    metrics = await MetricsEngine().aggregate(run_id, store)
    traces = await store.get_traces_v2(run_id) if hasattr(store, "get_traces_v2") else []
    results = _pipeline_results_from_traces(traces) if traces else await store.get_results(run_id)
    return {"run_id": run_id, "pipelines": _build_diagram(metrics, results)}


async def _get_pipeline_graph(run_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Canonical PipelineGraph projection (nodes + edges with CIs) from traces + metrics."""
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs

    store = _store(db_path)
    await store.init_db()
    agg = await MetricsEngine().aggregate(run_id, store)
    traces = await store.get_traces_v2(run_id) if hasattr(store, "get_traces_v2") else []
    graphs = build_pipeline_graphs(agg, traces)
    return {
        "run_id": run_id,
        "pipelines": [g.to_dict() for g in graphs],
    }


def _parse_trace_payload(payload: Dict[str, Any], run_id: str):
    from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2

    data = dict(payload)
    if run_id:
        data["run_id"] = run_id
    return RetrievalTraceV2.from_dict(data)


async def _push_traces(
    run_id: str,
    traces: List[Dict[str, Any]],
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Ingest V2 retrieval traces into a benchmark run (same contract as REST POST .../traces)."""
    store = _store(db_path)
    await store.init_db()
    stored: List[str] = []
    for payload in traces:
        trace = _parse_trace_payload(payload, run_id=run_id)
        await store.save_trace_v2(trace)
        stored.append(trace.trace_id)
    return {"run_id": run_id, "trace_ids": stored, "count": len(stored)}


_RETRIEVER_STUB = '''"""Custom retriever factory for retobs adapter.import.

Replace KeywordOverlapRetriever with your production retriever class.
Factory signature: (corpus, stage_cfg, **kwargs) -> (adapter, k)
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from retrieval_observatory.types import Document, Query, RetrievalResult


class KeywordOverlapRetriever:
    def __init__(self, corpus: Dict[str, str], retriever_id: str = "my_retriever"):
        self.retriever_id = retriever_id
        self._corpus = corpus

    def retrieve(self, query: Query) -> RetrievalResult:
        q_tokens = set(query.text.lower().split())
        scored = [
            (doc_id, len(q_tokens & set(text.lower().split())))
            for doc_id, text in self._corpus.items()
            if q_tokens & set(text.lower().split())
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: query.k]
        documents = [
            Document(id=doc_id, text=self._corpus[doc_id], score=float(score), rank=rank)
            for rank, (doc_id, score) in enumerate(top, start=1)
        ]
        return RetrievalResult(documents=documents, latency_ms=0.0, retriever_id=self.retriever_id)


def build_retriever(
    corpus: Optional[Dict[str, str]],
    stage_cfg: dict,
    **kwargs,
) -> Tuple[KeywordOverlapRetriever, int]:
    if corpus is None:
        raise ValueError("build_retriever requires a corpus from the dataset loader.")
    cfg = stage_cfg.get("config", {})
    k = int(cfg.get("k", 10))
    retriever_id = stage_cfg.get("retriever_id", "my_retriever")
    return KeywordOverlapRetriever(corpus, retriever_id=retriever_id), k
'''

_INSTRUMENT_STUB = '''"""retobs instrumentation stub — wire into your RAG pipeline."""
from __future__ import annotations

import retrieval_observatory as ro
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace

recorder = ro.init(service="my-rag", db=".retobs/prod.db")


@observe(op_type="SOURCE", op_id="my_retriever")
def retrieve(query: str):
  """Replace with your retrieval logic."""
  raise NotImplementedError("Wire your retriever here")


def traced_query(run_id: str, query_id: str, query_text: str) -> None:
    start_trace(
        ObserveContext(
            run_id=run_id,
            query_id=query_id,
            query_text=query_text,
            pipeline_id="main",
        )
    )
    retrieve(query_text)
    finish_trace()
'''


def _bootstrap_config_yaml(experiment_name: str, factory: str) -> str:
    return f"""experiment:
  name: {experiment_name}

dataset:
  type: custom
  name: custom
  queries_path: queries.jsonl
  corpus_path: corpus.jsonl
  qrels_path: qrels.jsonl

pipelines:
  - id: main
    stages:
      - type: adapter.import
        retriever_id: my_retriever
        config:
          factory: {factory}
          k: 10

metrics:
  recall_at_k: [5, 10]
  ndcg_at_k: [10]

output:
  store: sqlite
  db_path: .retobs/results.db
"""


async def _bootstrap_project(
    project_root: str,
    framework: str = "python",
    retriever_entrypoint: Optional[str] = None,
    experiment_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Scaffold retobs config and stubs in an external project directory."""
    root = Path(project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    retobs_dir = root / "retobs"
    retobs_dir.mkdir(parents=True, exist_ok=True)

    exp_name = experiment_name or Path(root.name).name or "my-rag"
    factory = retriever_entrypoint or "retriever.build_retriever"
    written: List[str] = []

    config_path = retobs_dir / "config.yaml"
    config_path.write_text(_bootstrap_config_yaml(exp_name, factory), encoding="utf-8")
    written.append(str(config_path))

    mcp_path = root / "retobs-mcp.yaml"
    mcp_path.write_text(
        "db_path: .retobs/results.db\nmax_queries: 50\nbaseline_run_id: null\n",
        encoding="utf-8",
    )
    written.append(str(mcp_path))

    if framework == "python":
        retriever_path = retobs_dir / "retriever.py"
        if not retriever_path.exists():
            retriever_path.write_text(_RETRIEVER_STUB, encoding="utf-8")
            written.append(str(retriever_path))
        instrument_path = retobs_dir / "instrument.py"
        if not instrument_path.exists():
            instrument_path.write_text(_INSTRUMENT_STUB, encoding="utf-8")
            written.append(str(instrument_path))

    guide = await _describe_integration(framework)
    return {
        "project_root": str(root),
        "framework": framework,
        "files_written": written,
        "config_path": str(config_path),
        "mcp_config_path": str(mcp_path),
        "next": [
            "Add queries.jsonl, corpus.jsonl, qrels.jsonl under retobs/ (or switch dataset to beir/...)",
            "validate_config with the generated config (use benchmark_config_file for on-disk YAML)",
            "benchmark_config_file(config_path=...)",
            "Wire instrument.py or describe_integration snippet into your pipeline",
            "push_traces then verify_integration",
        ],
        "integration_guide": guide,
    }


def build_server(config_path: Optional[str] = None):
    """Construct the FastMCP server with all retobs tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:  # pragma: no cover - exercised only without the extra
        FastMCP = _FallbackFastMCP

    server = FastMCP("retrieval-observatory")
    server.tool(name="describe_config")(_describe_config)
    server.tool(name="validate_config")(_validate_config)
    server.tool(name="describe_integration")(_describe_integration)
    server.tool(name="verify_integration")(_with_config_defaults(config_path, _verify_integration))
    server.tool(name="bootstrap_project")(_bootstrap_project)
    server.tool(name="push_traces")(_with_config_defaults(config_path, _push_traces))
    server.tool(name="list_runs")(_with_config_defaults(config_path, _list_runs))
    server.tool(name="get_run_metrics")(_with_config_defaults(config_path, _get_run_metrics))
    server.tool(name="benchmark_config")(_with_config_defaults(config_path, _benchmark_config))
    server.tool(name="benchmark_config_file")(_with_config_defaults(config_path, _benchmark_config_file))
    server.tool(name="benchmark_pipeline_descriptor")(_with_config_defaults(config_path, _benchmark_pipeline_descriptor))
    server.tool(name="benchmark_vs_baseline")(_with_config_defaults(config_path, _benchmark_vs_baseline))
    server.tool(name="get_pareto_frontier")(_with_config_defaults(config_path, _get_pareto_frontier))
    server.tool(name="get_recommendations")(_with_config_defaults(config_path, _get_recommendations))
    server.tool(name="get_operator_attribution")(_with_config_defaults(config_path, _get_operator_attribution))
    server.tool(name="get_pipeline_diagram")(_with_config_defaults(config_path, _get_pipeline_diagram))
    server.tool(name="get_pipeline_graph")(_with_config_defaults(config_path, _get_pipeline_graph))
    return server


def main(config_path: Optional[str] = None) -> None:
    """Entry point for `retobs mcp` — run the server over stdio."""
    build_server(config_path).run()


if __name__ == "__main__":
    main()
