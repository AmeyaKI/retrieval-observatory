from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.comparison import (
    _scores_for,
    compare_paired_metrics,
    comparison_validity,
    pipeline_pairs,
    parse_metric_key,
    rank_metric_keys,
)
from retrieval_observatory.metrics.diagnostics import aggregate_diagnostics
from retrieval_observatory.metrics.significance import benjamini_hochberg, bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.dashboard.registry import DbRegistry, hosted_read_only
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.postgres import PostgresStore
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.types import Document, StageSnapshot
from retrieval_observatory.config.diff import diff_configs
from retrieval_observatory.config.schema import ExperimentConfig
from dataclasses import asdict as _dataclass_asdict

_UI_DIST = os.path.join(os.path.dirname(__file__), "ui", "dist")

# Retired HTTP routes answer 410 with a migration message; the removed features never return
# fabricated results. Each entry: (path, replacement workspace, message).
_TEST_SETS_RETIRED = "Test set generation was retired. Connect covers benchmark setup for an existing retrieval pipeline; import prepared benchmarks instead."
_FINDINGS_RETIRED = "Recommendation, regression and reliability findings were retired. Audit compares a baseline and a candidate run against declared tolerances."
_DIFFICULTY_RETIRED = "Learned difficulty labels were retired. Investigate reports judgments and outcomes per query."
_TRADEOFFS_RETIRED = "Tradeoff views were retired. Audit compares a baseline and a candidate run, including latency, against declared tolerances."
_ATTRIBUTION_RETIRED = "Counterfactual replay and operator attribution were retired. Investigate shows each candidate's recorded transitions and loss boundary per query."
_MONITORING_RETIRED = "Production monitoring views were retired. Investigate reads the captured traces for a selected run."
_ANALYSIS_RETIRED = "Cohort and corpus-health analysis were retired. Investigate filters the retained evidence for a selected run."
_RETIRED_ROUTES: tuple[tuple[str, str, str], ...] = (
    *((f"{prefix}/forge/{{rest:path}}", "connect", _TEST_SETS_RETIRED) for prefix in ("/dbs/{db_id}", "")),
    *((f"{prefix}/advisor/{{rest:path}}", "audit", _FINDINGS_RETIRED) for prefix in ("/dbs/{db_id}", "")),
    *(
        (f"{prefix}/runs/{{run_id}}/{page}", replacement, message)
        for prefix in ("/dbs/{db_id}", "")
        for page, replacement, message in (
            ("query-labels", "investigate", _DIFFICULTY_RETIRED),
            ("classifier-calibration", "investigate", _DIFFICULTY_RETIRED),
            ("pareto-frontier", "audit", _TRADEOFFS_RETIRED),
            ("operator-attribution", "investigate", _ATTRIBUTION_RETIRED),
            ("traces/{trace_id}/miss-attribution", "investigate", _ATTRIBUTION_RETIRED),
            ("traces/{trace_id}/operator/{op_id}/diff", "investigate", _ATTRIBUTION_RETIRED),
            ("queries/{query_id}/candidates/{candidate_id}", "investigate", _ATTRIBUTION_RETIRED),
        )
    ),
    *(
        (f"{prefix}/production/{view}", "investigate", _MONITORING_RETIRED)
        for prefix in ("/dbs/{db_id}", "")
        for view in ("summary", "distribution", "drift", "hotspots", "clusters")
    ),
    ("/dbs/{db_id}/analysis/cohorts", "investigate", _ANALYSIS_RETIRED),
    ("/dbs/{db_id}/analysis/corpus-health", "investigate", _ANALYSIS_RETIRED),
)
# Never serve the SPA shell for these — browser would execute HTML as JS/CSS → blank page.
_STATIC_EXTENSIONS = (".js", ".css", ".map", ".ico", ".png", ".svg", ".woff", ".woff2", ".json", ".txt")


def _is_static_asset_path(path: str) -> bool:
    normalized = path.lstrip("/")
    if normalized.startswith("assets/"):
        return True
    return normalized.endswith(_STATIC_EXTENSIONS)


def _index_response(index_path: str):
    from fastapi.responses import FileResponse

    return FileResponse(
        index_path,
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


def _mean(values: List[float]) -> float:
    return sum(float(value) for value in values) / len(values) if values else 0.0


def _std(values: List[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return (sum((float(value) - avg) ** 2 for value in values) / len(values)) ** 0.5


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(100.0, percentile)) / 100.0 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)

try:
    from pydantic import BaseModel as _BaseModel

    class CompareRequest(_BaseModel):
        run_ids: List[str]
        policy_path: Optional[str] = None

    class RunSelection(_BaseModel):
        db_id: str
        run_id: str
        role: Optional[Literal["baseline", "candidate", "reference"]] = None

    class MultiCompareRequest(_BaseModel):
        selections: List[RunSelection]
        policy_path: Optional[str] = None

    class EdgeRequest(_BaseModel):
        src_doc_id: str
        dst_doc_id: str
        edge_type: str
        weight: float = 1.0
except ImportError:
    CompareRequest = None  # type: ignore
    RunSelection = None  # type: ignore
    MultiCompareRequest = None  # type: ignore
    EdgeRequest = None  # type: ignore


def _selection_key(db_id: str, run_id: str) -> str:
    return f"{db_id}/{run_id}"


async def _resolve_qrels(store: Any, run_id: str) -> Dict[str, Dict[str, int]]:
    """Ground truth for a run, for operator attribution and miss attribution.

    Prefers run_qrels (persisted once per run by execute_benchmark — see
    runner/execute.py::execute_benchmark). Falls back to the legacy
    query_metadata.qrel_ids convention on metric_scores rows for runs persisted
    before run_qrels existed; that field is never written by the standard
    benchmark path but some callers set it manually (e.g. production-trace-only
    runs seeding qrels by hand).
    """
    if hasattr(store, "get_qrels"):
        qrels = await store.get_qrels(run_id)
        if qrels:
            return qrels
    metrics_rows = await store.get_metrics(run_id)
    qrels: Dict[str, Dict[str, int]] = {}
    for row in metrics_rows:
        rel = row.get("query_metadata", {}).get("qrel_ids")
        if isinstance(rel, list):
            qrels.setdefault(row["query_id"], {doc_id: 1 for doc_id in rel})
    return qrels


@dataclass
class _CompatResult:
    query_id: str
    pipeline_id: str
    snapshots: List[StageSnapshot]
    total_latency_ms: float
    status: str
    error_traceback: str | None = None


def _pipeline_results_from_traces(traces: List[RetrievalTrace]) -> List[_CompatResult]:
    """Adapt trace-native spans into legacy StageSnapshot rows for the per-query results
    endpoint (`/runs/{id}/queries/{query_id}`), which still renders a flat per-stage
    document list.

    Stage index must come from position in trace.spans (the pipeline's fixed op
    order), not from enumerating FIRED-only spans -- a gated stage (e.g. EXPAND)
    fires for some queries and not others, so filtering first would shift every
    later stage's index per-trace and corrupt cross-trace alignment. A SKIPPED_BY_GATE
    span still gets a snapshot; its own outputs (a passthrough of its inputs) honestly
    reflect that it was a no-op for that query.
    """
    results: List[_CompatResult] = []
    for trace in traces:
        snapshots: List[StageSnapshot] = []
        for idx, span in enumerate(trace.spans):
            docs = [
                Document(id=c.doc_id, text="", score=c.score, rank=c.rank)
                for c in span.outputs
            ]
            snapshots.append(
                StageSnapshot(
                    stage_index=idx,
                    stage_id=span.op_id,
                    documents=docs,
                    latency_ms=span.latency_ms,
                    candidate_count=len(docs),
                    op_type=span.op_type,
                )
            )
        results.append(
            _CompatResult(
                query_id=trace.query_id,
                pipeline_id=trace.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=trace.timing.wall_clock_ms,
                status=trace.status,
                error_traceback=trace.error_traceback,
            )
        )
    return results


# Top-level keys of a production trace as the retained trace list/detail routes return it.
# Those endpoints map every trace through _monitor_trace so this shape cannot drift silently;
# tests/unit/test_dashboard_production_contract.py asserts it against real responses.
PRODUCTION_TRACE_ROW_KEYS = frozenset({
    "trace_id", "service", "service_id", "query_id", "query_text", "pipeline_id", "status",
    "total_latency_ms", "timestamp", "predicted_difficulty", "suspected_failures", "metadata",
})
PRODUCTION_TRACE_DETAIL_KEYS = PRODUCTION_TRACE_ROW_KEYS | {"stages", "spans", "timing"}
PRODUCTION_TRACE_STAGE_KEYS = frozenset({"stage_index", "stage_id", "latency_ms", "candidate_count", "documents"})
PRODUCTION_SERVICE_KEYS = frozenset({"service", "service_id", "trace_count", "last_seen"})


def _monitor_trace(trace: RetrievalTrace) -> Dict[str, Any]:
    """Flatten a trace into the list/detail shape of the retained trace routes.

    Keeps the raw ``spans``/``timing``/``metadata`` from ``to_dict`` and adds the flattened
    fields (``service``, ``total_latency_ms``, ``predicted_difficulty``,
    ``suspected_failures``, ``stages``) the list/detail views render.
    """
    payload = trace.to_dict()
    payload["service"] = trace.service_id
    payload["total_latency_ms"] = (
        trace.timing.wall_clock_ms if trace.timing is not None else sum(span.latency_ms for span in trace.spans)
    )
    payload["predicted_difficulty"] = trace.metadata.get("predicted_difficulty")
    payload["suspected_failures"] = list(trace.metadata.get("suspected_failures", []) or [])
    payload["stages"] = [
        {
            "stage_index": index,
            "stage_id": span.op_id,
            "op_type": span.op_type,
            "status": span.status,
            "latency_ms": span.latency_ms,
            "candidate_count": len(span.outputs),
            "documents": [
                {"id": candidate.doc_id, "score": candidate.score, "rank": candidate.rank}
                for candidate in span.outputs
            ],
        }
        for index, span in enumerate(trace.spans)
    ]
    return payload


class _AggregateCache:
    """Small in-process LRU for ``MetricsEngine.aggregate`` keyed by (db_id, run_id, metric-row count).

    Metric rows are append-only, so a run's row count is a sufficient fingerprint: a recompute
    or a new pipeline adds rows and busts the entry. Bootstrap CIs dominate aggregate cost
    (seconds on a 30k-row run), and every run page fans out to several endpoints that all
    need the same aggregate.
    """

    def __init__(self, engine: MetricsEngine, maxsize: int = 32):
        self._engine = engine
        self._maxsize = maxsize
        self._entries: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()

    @staticmethod
    async def _row_count(store: Any, run_id: str) -> int | None:
        try:
            if isinstance(store, SQLiteStore):
                async with store._connect() as db:
                    async with db.execute(
                        "SELECT COUNT(*) FROM metric_scores WHERE run_id = ?", (run_id,)
                    ) as cursor:
                        row = await cursor.fetchone()
                return int(row[0]) if row else 0
            if isinstance(store, PostgresStore):
                pool = await store._get_pool()
                async with pool.acquire() as conn:
                    return int(await conn.fetchval("SELECT COUNT(*) FROM metric_scores WHERE run_id = $1", run_id))
        except Exception:
            return None
        return None

    async def get(self, db_id: str, run_id: str, store: Any) -> Dict[str, Any]:
        async def compute() -> Dict[str, Any]:
            return await self._engine.aggregate(run_id, store)

        return dict(await self.cached(db_id, run_id, store, "aggregate", compute))

    async def cached(self, db_id: str, run_id: str, store: Any, name: str, compute: Any) -> Any:
        """Memoise any pure derivation of a run's metric rows under the same fingerprint."""
        count = await self._row_count(store, run_id)
        if count is None:
            return await compute()
        key = (db_id, run_id, count, name)
        if key in self._entries:
            self._entries.move_to_end(key)
            return self._entries[key]
        value = await compute()
        self._entries[key] = value
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)
        return value


class _MetricsCaptureStore:
    """Read-through proxy that keeps freshly computed metric rows in memory.

    Used by ``GET .../metrics`` on a read-only registry: the engine can compute metrics from
    traces without the store ever seeing a write.
    """

    def __init__(self, store: Any):
        self._store = store
        self.rows: List[Dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def save_metrics_batch(self, rows: List[Dict[str, Any]]) -> None:
        self.rows.extend(rows)

    async def save_metric(self, **row: Any) -> None:
        row["query_metadata_json"] = row.pop("query_metadata", None)
        self.rows.append(row)

    async def get_metrics(self, run_id: str) -> List[Dict[str, Any]]:
        persisted = await self._store.get_metrics(run_id)
        captured = [
            {**row, "query_metadata": row.get("query_metadata_json") or {}}
            for row in self.rows
            if row.get("run_id") == run_id
        ]
        return persisted + captured


def _comparability_report(manifests: List[Dict[str, Any] | None]) -> Dict[str, Any]:
    return comparison_validity(manifests).to_dict()


def _pick_primary_quality_metric(
    metric_keys: List[str],
    metrics_a: List[Dict[str, Any]],
    metrics_b: List[Dict[str, Any]],
) -> Optional[str]:
    """Pick the metric_key to drive the query-level winners/losers table: prefer ndcg over
    recall, prefer the largest k, and require at least one query scored in both runs."""
    candidates = []
    for key in metric_keys:
        try:
            pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(key)
        except ValueError:
            continue
        if metric_name not in ("ndcg", "recall") or branch_id is not None:
            continue
        scores_a = _scores_for(metrics_a, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
        scores_b = _scores_for(metrics_b, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
        if not (set(scores_a) & set(scores_b)):
            continue
        candidates.append((metric_name == "ndcg", k, key))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


async def _query_diffs(
    selections: List[tuple],
    registry: DbRegistry,
    all_metric_keys: List[str],
) -> Optional[Dict[str, Any]]:
    """Item D.1: per-query outcome deltas for the primary quality metric between exactly two
    runs, sorted by |delta| descending -- the winners/losers table that anchors Run
    Comparison's query-level diff section, each row linkable to the Query Diff View."""
    if len(selections) != 2:
        return None
    (db_a, run_a), (db_b, run_b) = selections
    store_a = registry.get_store(db_a)
    store_b = registry.get_store(db_b)
    metrics_a = await store_a.get_metrics(run_a)
    metrics_b = await store_b.get_metrics(run_b)
    metric_key = _pick_primary_quality_metric(all_metric_keys, metrics_a, metrics_b)
    if not metric_key:
        return None
    pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(metric_key)
    scores_a = _scores_for(metrics_a, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
    scores_b = _scores_for(metrics_b, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
    common = sorted(set(scores_a) & set(scores_b))
    # delta = candidate - baseline, matching orientation.effect == "candidate_minus_baseline"
    # on the comparison payload: positive means the candidate scored higher on that query.
    rows = [
        {"query_id": qid, "a": scores_a[qid], "b": scores_b[qid], "delta": scores_b[qid] - scores_a[qid]}
        for qid in common
    ]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {
        "metric": metric_key,
        "run_a": run_a,
        "run_b": run_b,
        "orientation": {
            "a": "baseline",
            "b": "candidate",
            "effect": "candidate_minus_baseline",
            "baseline": {"db_id": db_a, "run_id": run_a},
            "candidate": {"db_id": db_b, "run_id": run_b},
        },
        "rows": rows[:50],
    }


async def _build_comparison(
    selections: List[tuple],
    registry: DbRegistry,
    engine: MetricsEngine,
    policy_path: str | None = None,
    aggregate_cache: "_AggregateCache | None" = None,
) -> Dict[str, Any]:
    """Compare runs across one or more databases. selections: [(db_id, run_id), ...]."""
    if len(selections) < 2:
        raise ValueError("Provide at least 2 runs")

    warnings: List[str] = []
    manifests: List[Dict[str, Any] | None] = []
    for db_id, run_id in selections:
        store = registry.get_store(db_id)
        manifest = await store.get_run_manifest(run_id)
        manifests.append(manifest)
    validity = comparison_validity(manifests)
    comparability = validity.to_dict()
    warnings.extend(difference.detail for difference in validity.differences)

    keys = [_selection_key(db_id, run_id) for db_id, run_id in selections]
    aggregated: Dict[str, Dict] = {}
    metric_rows: Dict[str, List[Dict[str, Any]]] = {}
    for (db_id, run_id), key in zip(selections, keys):
        store = registry.get_store(db_id)
        aggregated[key] = (
            await aggregate_cache.get(db_id, run_id, store)
            if aggregate_cache is not None
            else await engine.aggregate(run_id, store)
        )
        metric_rows[key] = await store.get_metrics(run_id)

    # Decision-relevant rows first: a plain sort buries terminal-stage quality behind every
    # run-level operational row. Policy-guarded metrics lead when a policy is attached.
    policy_metrics: list[str] = []
    if policy_path:
        from retrieval_observatory.release.policy import load_release_policy as _load_policy

        try:
            policy_metrics = [guard.metric for guard in _load_policy(policy_path).metrics]
        except (OSError, ValueError):
            policy_metrics = []
    all_metric_keys = rank_metric_keys(
        set().union(*(agg.keys() for agg in aggregated.values())),
        policy_metrics=policy_metrics,
    )
    comparison = []
    paired_results = {}
    if len(selections) == 2:
        paired_results = compare_paired_metrics(
            metric_rows[keys[0]],
            metric_rows[keys[1]],
            all_metric_keys,
            validity,
        )

    for metric_key in all_metric_keys:
        entry: Dict[str, Any] = {"metric": metric_key}
        for key in keys:
            agg = aggregated[key].get(metric_key, {})
            entry[key] = {
                "mean": agg.get("mean"),
                "std": agg.get("std"),
                "ci_low": agg.get("ci_low"),
                "ci_high": agg.get("ci_high"),
            }
        if metric_key in paired_results:
            statistics = paired_results[metric_key].to_dict()
            entry["statistics"] = statistics
            entry["p_value"] = statistics["p_value"]
            entry["q_value"] = statistics["q_value"]
            entry["paired_n"] = statistics["paired_n"]
        comparison.append(entry)

    query_diffs = await _query_diffs(selections, registry, all_metric_keys) if validity.decision_allowed else None
    release_decision = audit = None
    if len(selections) == 2:
        from retrieval_observatory.release.audit import build_release_audit
        from retrieval_observatory.release.policy import load_release_policy

        (baseline_db_id, baseline_run_id), (candidate_db_id, candidate_run_id) = selections
        report, audit = await build_release_audit(
            registry.get_store(baseline_db_id),
            registry.get_store(candidate_db_id),
            baseline_run_id,
            candidate_run_id,
            policy=load_release_policy(policy_path) if policy_path else None,
            policy_source=policy_path,
            baseline_db_id=baseline_db_id,
            candidate_db_id=candidate_db_id,
        )
        affected_query_ids = [row["query_id"] for row in (query_diffs or {}).get("rows", [])]
        release_decision = {
            **(report.comparison or {})["release_decision"],
            "investigation": {
                "affected_query_ids": affected_query_ids,
                "query_route_template": f"#/runs/{quote(str(candidate_run_id), safe='')}/queries/{{query_id}}",
                "diff_route_template": (
                    f"#/runs/{quote(str(candidate_run_id), safe='')}/queries/{{query_id}}/diff?against="
                    f"{quote(str(baseline_run_id), safe='')}"
                    f"&against_db={quote(str(baseline_db_id), safe='')}"
                    + (
                        f"&policy_path={quote(policy_path, safe='')}"
                        if policy_path
                        else ""
                    )
                ),
            },
        }

    return {
        "comparison": comparison,
        "selections": [
            {"db_id": db_id, "run_id": run_id, "role": "baseline" if index == 0 else "candidate" if index == 1 else "reference"}
            for index, (db_id, run_id) in enumerate(selections)
        ],
        "orientation": {
            "baseline": {"db_id": selections[0][0], "run_id": selections[0][1]},
            "candidate": {"db_id": selections[1][0], "run_id": selections[1][1]},
            "effect": "candidate_minus_baseline",
        } if len(selections) == 2 else None,
        "run_ids": [run_id for _, run_id in selections],
        "warnings": warnings,
        "comparability": comparability,
        "query_diffs": query_diffs,
        "release_decision": release_decision,
        "audit": audit,
    }


def create_app(
    registry: DbRegistry | None = None,
    db_path: str | None = None,
    db_paths: List[str] | None = None,
    enable_uploads: bool = True,
):
    try:
        from fastapi import APIRouter, Body, Depends, FastAPI, File, Header, HTTPException, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as e:
        raise ImportError("Dashboard requires fastapi. Install with: pip install fastapi") from e

    # Optional bearer-token auth (local-first: off unless RETOBS_API_TOKEN is set). Gates the
    # expensive write/run endpoints only; reads stay open so the dashboard SPA keeps working.
    _api_token = os.environ.get("RETOBS_API_TOKEN")

    def _require_auth(authorization: str | None = Header(default=None)) -> None:
        if not _api_token:
            return
        expected = f"Bearer {_api_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    if registry is None:
        paths = db_paths if db_paths else ([db_path] if db_path else [".retobs/results.db"])
        registry = DbRegistry(paths)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await registry.init_all()
        yield

    from importlib.metadata import PackageNotFoundError, version

    try:
        package_version = version("retrieval-observatory")
    except PackageNotFoundError:
        package_version = "0+unknown"
    app = FastAPI(title="Retrieval Observatory", version=package_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from starlette.responses import JSONResponse

    _read_only = hosted_read_only()
    if _read_only:
        enable_uploads = False

    _READ_ONLY_POST_ALLOW = frozenset({"/compare", "/compare/config-diff"})

    if _read_only:

        @app.middleware("http")
        async def _hosted_demo_read_only(request, call_next):
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                path = request.url.path.rstrip("/") or "/"
                if path not in _READ_ONLY_POST_ALLOW:
                    return JSONResponse({"detail": "Hosted demo is read-only"}, status_code=403)
            return await call_next(request)

    # Per-IP sliding-window rate limit. On by default only in hosted read-only mode, where the
    # app sits behind an ingress that sets X-Forwarded-For; off locally (0) unless configured.
    _rate_limit = int(os.environ.get("RETOBS_RATE_LIMIT_PER_MINUTE", "300" if _read_only else "0"))
    if _rate_limit > 0:
        import time
        from collections import deque

        _hits: Dict[str, deque] = {}

        def _client_ip(request) -> str:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return request.client.host if request.client else "unknown"

        @app.middleware("http")
        async def _per_ip_rate_limit(request, call_next):
            now = time.monotonic()
            window_start = now - 60.0
            hits = _hits.setdefault(_client_ip(request), deque())
            while hits and hits[0] < window_start:
                hits.popleft()
            if len(hits) >= _rate_limit:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
            hits.append(now)
            if len(_hits) > 10_000:
                for key in [key for key, value in _hits.items() if not value or value[-1] < window_start]:
                    _hits.pop(key, None)
            return await call_next(request)

    def _reject_policy_path(policy_path: str | None) -> None:
        """A policy file path is a server filesystem path; never accept one from the network in hosted mode."""
        if _read_only and policy_path:
            raise HTTPException(status_code=403, detail="policy_path is not accepted by the hosted read-only dashboard")

    def _bound(name: str, value: int, low: int, high: int) -> int:
        if not low <= value <= high:
            raise HTTPException(status_code=422, detail=f"{name} must be {low}..{high}")
        return value

    def _iso_or_422(name: str, value: str):
        from datetime import datetime

        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{name} must be an ISO-8601 timestamp")

    @app.get("/healthz")
    async def healthz() -> Dict[str, Any]:
        return {"status": "ok", "read_only": _read_only, "databases": len(registry.list_db_ids())}

    engine = MetricsEngine()
    aggregate_cache = _AggregateCache(engine)
    default_store = registry.get_store(registry.default_db_id)  # type: ignore[arg-type]

    async def _aggregate(db_id: str, run_id: str, store: Any) -> Dict[str, Any]:
        return await aggregate_cache.get(db_id, run_id, store)

    # In-process benchmark job tracking. Runs are triggered via POST /dbs/{db_id}/runs and
    # execute in the background (execute_benchmark is async); status is polled via
    # GET /dbs/{db_id}/runs/{run_id}/status. A small concurrency cap protects against an agent
    # firing many expensive runs at once — the real rate-limit concern for a local-first tool.
    _jobs: Dict[str, Dict[str, Any]] = {}
    _max_concurrent_runs = int(os.environ.get("RETOBS_MAX_CONCURRENT_RUNS", "2"))

    def _active_run_count() -> int:
        return sum(1 for job in _jobs.values() if job.get("status") == "running")

    def _store_for(db_id: str):
        try:
            return registry.get_store(db_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown database '{db_id}'")

    @app.get("/dbs")
    async def list_databases() -> List[Dict]:
        return await registry.list_sources()

    @app.get("/demo/context")
    async def get_demo_context() -> Dict[str, Any]:
        from retrieval_observatory.dashboard.demo_context import find_demo_context_for_registry

        context = find_demo_context_for_registry(registry.db_paths)
        if not context:
            return context
        demo_path = context.get("db_path")
        for candidate_db_id in registry.list_db_ids():
            if registry.get(candidate_db_id).path == demo_path:
                context["db_id"] = candidate_db_id
                break
        if registry.read_only or _read_only:
            # Hosted read-only mode never reveals container filesystem paths.
            context.pop("db_path", None)
        return context

    @app.post("/compare")
    async def compare_runs_endpoint(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if "selections" in body:
            parsed = MultiCompareRequest.model_validate(body)
            policy_path = parsed.policy_path
            if len(parsed.selections) < 2:
                raise HTTPException(status_code=400, detail="Provide at least 2 run selections")
            roles = [selection.role for selection in parsed.selections if selection.role]
            if roles:
                if roles.count("baseline") != 1 or roles.count("candidate") != 1:
                    raise HTTPException(status_code=400, detail="Comparison roles require exactly one baseline and one candidate")
                ordered = sorted(
                    parsed.selections,
                    key=lambda selection: {"baseline": 0, "candidate": 1}.get(selection.role or "reference", 2),
                )
            else:
                ordered = parsed.selections
            selections = [(selection.db_id, selection.run_id) for selection in ordered]
        elif "run_ids" in body:
            if not registry.is_single:
                raise HTTPException(
                    status_code=400,
                    detail="run_ids compare requires a single loaded database; use selections with db_id",
                )
            parsed_legacy = CompareRequest.model_validate(body)
            policy_path = parsed_legacy.policy_path
            if len(parsed_legacy.run_ids) < 2:
                raise HTTPException(status_code=400, detail="Provide at least 2 run IDs")
            sole = registry.default_db_id
            selections = [(sole, run_id) for run_id in parsed_legacy.run_ids]
        else:
            raise HTTPException(status_code=400, detail="Provide selections or run_ids")
        _reject_policy_path(policy_path)
        for db_id, _ in selections:
            _store_for(db_id)
        try:
            result = await _build_comparison(
                selections,
                registry,
                engine,
                policy_path=policy_path,
                aggregate_cache=aggregate_cache,
            )
        except (OSError, TypeError, ValueError) as exc:
            label = "Comparison failed" if "Run not found" in str(exc) else "Invalid local release policy"
            raise HTTPException(status_code=422, detail=f"{label}: {exc}") from exc
        if "run_ids" in body and registry.is_single:
            result["run_ids"] = body["run_ids"]
        return result

    @app.post("/compare/config-diff")
    async def compare_config_diff(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Item D.5: structural config diff between exactly two runs, wiring the already-
        built config/diff.py::diff_configs over the runs' stored config_json."""
        parsed = MultiCompareRequest.model_validate(body)
        if len(parsed.selections) != 2:
            raise HTTPException(status_code=400, detail="Config diff requires exactly 2 run selections")
        configs: List[ExperimentConfig] = []
        for sel in parsed.selections:
            store = _store_for(sel.db_id)
            run_rows = [run for run in await store.list_runs() if run["run_id"] == sel.run_id]
            if not run_rows:
                raise HTTPException(status_code=404, detail=f"Run '{sel.run_id}' not found in '{sel.db_id}'")
            try:
                configs.append(ExperimentConfig.model_validate_json(run_rows[0]["config_json"]))
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Run '{sel.run_id}' has a stored config that doesn't parse as an ExperimentConfig: {e}",
                )
        diff = diff_configs(configs[0], configs[1])
        return {
            "dataset_changed": diff.dataset_changed,
            "metrics_changed": diff.metrics_changed,
            "has_changes": diff.has_changes,
            "pipeline_diffs": [_dataclass_asdict(p) for p in diff.pipeline_diffs],
        }

    @app.post("/experiments/{name}/runs")
    async def create_remote_run(name: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if not registry.default_db_id:
            raise HTTPException(status_code=503, detail="No default database configured")
        store = registry.get_store(registry.default_db_id)
        await store.init_db()
        run_id = str(uuid.uuid4())[:8]
        config_json = payload.get("config_json", "{}")
        await store.save_run(run_id=run_id, experiment_name=name, config_json=config_json)
        return {"run_id": run_id, "experiment_name": name}

    @app.post("/runs/{run_id}/results")
    async def remote_push_results(run_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if not registry.default_db_id:
            raise HTTPException(status_code=503, detail="No default database configured")
        store = registry.get_store(registry.default_db_id)
        await store.init_db()
        traces = payload.get("traces", [])
        ingested = 0
        for item in traces:
            trace = _parse_trace(item, run_id=run_id)
            await store.save_trace(trace)
            ingested += 1
        return {"run_id": run_id, "ingested": ingested}

    @app.post("/runs/{run_id}/metrics")
    async def remote_push_metrics(run_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if not registry.default_db_id:
            raise HTTPException(status_code=503, detail="No default database configured")
        store = registry.get_store(registry.default_db_id)
        await store.init_db()
        rows = payload.get("rows", [])
        for row in rows:
            row.setdefault("run_id", run_id)
        await store.save_metrics_batch(rows)
        return {"run_id": run_id, "stored": len(rows)}

    @app.post("/runs/{run_id}/finish")
    async def remote_finish_run(run_id: str) -> Dict[str, Any]:
        if not registry.default_db_id:
            raise HTTPException(status_code=503, detail="No default database configured")
        store = registry.get_store(registry.default_db_id)
        await store.init_db()
        await store.finish_run(run_id)
        return {"run_id": run_id, "finished": True}

    db_router = APIRouter(prefix="/dbs/{db_id}")

    @db_router.get("/runs")
    async def list_runs(db_id: str) -> List[Dict]:
        store = _store_for(db_id)
        runs = await registry.list_runs(db_id)
        enriched = []
        for run in runs:
            manifest = await store.get_run_manifest(run["run_id"]) or {}
            if manifest.get("golden_set"):
                run = {**run, "golden_set": manifest["golden_set"]}
            enriched.append(run)
        return enriched

    @db_router.post("/compare")
    async def compare_runs_in_db(db_id: str, req: CompareRequest) -> Dict[str, Any]:
        if len(req.run_ids) < 2:
            raise HTTPException(status_code=400, detail="Provide at least 2 run IDs")
        _reject_policy_path(req.policy_path)
        _store_for(db_id)
        selections = [(db_id, run_id) for run_id in req.run_ids]
        try:
            return await _build_comparison(
                selections,
                registry,
                engine,
                policy_path=req.policy_path,
                aggregate_cache=aggregate_cache,
            )
        except (OSError, TypeError, ValueError) as exc:
            label = "Comparison failed" if "Run not found" in str(exc) else "Invalid local release policy"
            raise HTTPException(status_code=422, detail=f"{label}: {exc}") from exc

    @db_router.get("/runs/{run_id}/metrics")
    async def get_run_metrics(db_id: str, run_id: str, include_branches: bool = False) -> Dict[str, Any]:
        store = _store_for(db_id)
        agg = await _aggregate(db_id, run_id, store)
        # Run-level status rows (stage -1) exist as soon as traces do; only per-stage rows
        # prove metrics were computed.
        if not any(entry.get("stage_index", -1) != -1 for entry in agg.values()):
            traces = await store.list_traces(TraceQuery(run_id=run_id))
            if traces:
                qrels = await _resolve_qrels(store, run_id)
                if registry.read_only or _read_only:
                    # A read-only store must never be written by a GET: compute the rows into
                    # an in-memory sink and aggregate from there.
                    sink = _MetricsCaptureStore(store)
                    await engine.compute_from_traces(run_id, sink, traces, qrels)
                    agg = await engine.aggregate(run_id, sink)
                else:
                    await engine.compute_from_traces(run_id, store, traces, qrels)
                    agg = await _aggregate(db_id, run_id, store)
        if not include_branches:
            agg = {k: v for k, v in agg.items() if not v.get("branch_id")}
        if not agg:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")
        return agg

    @db_router.get("/runs/{run_id}/metrics/by-segment")
    async def get_run_metrics_by_segment(db_id: str, run_id: str, field: str = "n_relevant") -> Dict[str, Any]:
        """Return per-segment aggregated metrics grouped by a query metadata field."""
        store = _store_for(db_id)
        raw_metrics = await store.get_metrics(run_id)
        if not raw_metrics:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")

        # Group by (segment_value, pipeline_id, stage_index, metric_name, k)
        groups: Dict[tuple, list] = defaultdict(list)
        for row in raw_metrics:
            if row.get("branch_id"):
                continue
            meta = row.get("query_metadata") or {}
            seg_val = meta.get(field)
            if seg_val is None:
                continue
            key = (str(seg_val), row["pipeline_id"], row["stage_index"], row["metric_name"], row["k"])
            groups[key].append(row["value"])

        result: Dict[str, Any] = {}
        for (seg_val, pipeline_id, stage_index, metric_name, k), scores in groups.items():
            ci_low, ci_high = bootstrap_ci(scores)
            metric_key = f"{pipeline_id}|stage{stage_index}|{metric_name}@{k}"
            result.setdefault(seg_val, {})[metric_key] = {
                "pipeline_id": pipeline_id,
                "stage_index": stage_index,
                "metric_name": metric_name,
                "k": k,
                "mean": _mean(scores),
                "std": _std(scores),
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n": len(scores),
            }

        return {"field": field, "segments": result}

    # Published BEIR baselines (graded NDCG, BM25 Elasticsearch unless noted).
    # Source: Thakur et al. 2021 (https://arxiv.org/abs/2104.08663), Table 2.
    _BEIR_BASELINES: Dict[str, Dict[str, float]] = {
        "nfcorpus":        {"ndcg@10": 0.326, "recall@10": 0.175, "recall@100": 0.290},
        "trec-covid":      {"ndcg@10": 0.656, "recall@10": 0.493},
        "nq":              {"ndcg@10": 0.329, "recall@10": 0.527},
        "hotpotqa":        {"ndcg@10": 0.603, "recall@10": 0.756},
        "fiqa":            {"ndcg@10": 0.236, "recall@10": 0.323},
        "arguana":         {"ndcg@10": 0.472, "recall@10": 0.903},
        "quora":           {"ndcg@10": 0.789, "recall@10": 0.921},
        "dbpedia-entity":  {"ndcg@10": 0.313, "recall@10": 0.380},
        "scidocs":         {"ndcg@10": 0.158, "recall@10": 0.254},
        "fever":           {"ndcg@10": 0.753, "recall@10": 0.930},
        "climate-fever":   {"ndcg@10": 0.213, "recall@10": 0.394},
        "scifact":         {"ndcg@10": 0.665, "recall@10": 0.920},
        "trec-news":       {"ndcg@10": 0.397, "recall@10": 0.421},
    }

    @app.get("/datasets/{dataset_name}/baselines")
    async def get_baselines(dataset_name: str) -> Dict[str, float]:
        """Return published BM25 (Elasticsearch) BEIR baselines for a dataset."""
        # Strip "beir/" prefix if present
        name = dataset_name.removeprefix("beir/")
        return _BEIR_BASELINES.get(name, {})

    @db_router.get("/runs/{run_id}/manifest")
    async def get_manifest(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        manifest = await store.get_run_manifest(run_id)
        if not manifest:
            raise HTTPException(status_code=404, detail=f"No manifest for run '{run_id}'")
        return manifest

    @db_router.get("/runs/{run_id}/diagnostics")
    async def get_diagnostics(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        rows = await store.get_query_diagnostics(run_id)
        return {"summary": aggregate_diagnostics(rows), "items": rows}

    @db_router.get("/runs/{run_id}/overview")
    async def get_run_overview(db_id: str, run_id: str) -> Dict[str, Any]:
        from retrieval_observatory.sdk.report import build_run_report

        store = _store_for(db_id)
        runs = [run for run in await store.list_runs() if run["run_id"] == run_id]
        if not runs:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        metrics = await _aggregate(db_id, run_id, store)
        metrics_rows = await store.get_metrics(run_id)
        diagnostics = await store.get_query_diagnostics(run_id)
        manifest = await store.get_run_manifest(run_id)
        best = _headline_winner(metrics)

        async def _stage_contributions() -> List[Dict[str, Any]]:
            # Paired bootstrap tests over every layer and arm dominate /overview; the result
            # is a pure function of the run's metric rows, so it shares the aggregate memo.
            parent_map = await _pipeline_parent_map(store, run_id, metrics)
            return _compute_stage_contributions(metrics, metrics_rows, parent_map=parent_map)

        stage_contributions = await aggregate_cache.cached(db_id, run_id, store, "stage_contributions", _stage_contributions)
        report = build_run_report(
            run_id=run_id,
            experiment_name=runs[0].get("experiment_name", run_id),
            db_path=registry.get(db_id).path,
            metrics=metrics,
            diagnostics=diagnostics,
            manifest=manifest,
        )
        return {
            "run": runs[0],
            "report": report.to_dict(),
            "headline_winner": best,
            "diagnostics": aggregate_diagnostics(diagnostics),
            "manifest": manifest,
            "warnings": _overview_warnings(metrics, diagnostics, manifest),
            "stage_contributions": stage_contributions,
        }

    @db_router.get("/runs/{run_id}/report")
    async def get_run_report(db_id: str, run_id: str) -> Dict[str, Any]:
        """Canonical conclusion/evidence/provenance model for UI and agent clients."""
        overview = await get_run_overview(db_id, run_id)
        return overview["report"]

    @db_router.get("/runs/{run_id}/queries/{query_id}")
    async def get_query_result(db_id: str, run_id: str, query_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        traces = await store.list_traces(TraceQuery(run_id=run_id, query_id=query_id))
        results = [r for r in _pipeline_results_from_traces(traces) if r.query_id == query_id]
        diagnostics = [finding.to_dict() for finding in await store.query_diagnostics(run_id, query_id=query_id)]
        return {
            "run_id": run_id,
            "query_id": query_id,
            "diagnostics": diagnostics,
            "results": [
                {
                    "pipeline_id": result.pipeline_id,
                    "status": result.status,
                    "total_latency_ms": result.total_latency_ms,
                    "stages": [
                        {
                            "stage_index": snap.stage_index,
                            "stage_id": snap.stage_id,
                            "latency_ms": snap.latency_ms,
                            "profiling": snap.profiling,
                            "candidate_count": snap.candidate_count,
                            "documents": [
                                {"id": doc.id, "score": doc.score, "rank": doc.rank}
                                for doc in snap.documents
                            ],
                        }
                        for snap in result.snapshots
                    ],
                }
                for result in results
            ],
        }

    async def _query_lineage_payload(db_id: str, run_id: str, query_id: str) -> Dict[str, Any]:
        from retrieval_observatory.dashboard.analysis_api import build_query_lineage_payload

        store = _store_for(db_id)
        traces = await store.list_traces(TraceQuery(run_id=run_id, query_id=query_id))
        if not traces:
            raise HTTPException(
                status_code=404,
                detail=f"No traces for query '{query_id}' in run '{run_id}'",
            )
        qrels = await _resolve_qrels(store, run_id)
        manifest = await store.get_run_manifest(run_id) or {}
        mapping_coverage = (
            ((manifest.get("evidence_profile") or {}).get("lineage") or {}).get(
                "qrel_to_chunk_mapping_coverage"
            )
        )
        return build_query_lineage_payload(
            run_id=run_id,
            query_id=query_id,
            traces=traces,
            qrels_for_query=qrels.get(query_id, {}),
            qrel_chunk_mapping_complete=mapping_coverage == 1.0,
        )

    @db_router.get("/runs/{run_id}/queries/{query_id}/candidate-lineage")
    async def get_candidate_lineage(db_id: str, run_id: str, query_id: str) -> Dict[str, Any]:
        return await _query_lineage_payload(db_id, run_id, query_id)

    @db_router.get("/runs/{run_id}/queries/{query_id}/candidate-lineage-diff")
    async def get_candidate_lineage_diff(
        db_id: str,
        run_id: str,
        query_id: str,
        against: str,
        policy_path: str | None = None,
        against_db_id: str | None = None,
    ) -> Dict[str, Any]:
        """Stage-level lineage diff of one query between a candidate run (this db) and a baseline
        run read from ``against_db_id`` (default: the same database)."""
        from dataclasses import asdict

        from retrieval_observatory.release.assessment import assess_evidence
        from retrieval_observatory.release.policy import load_release_policy
        from retrieval_observatory.tracing.lineage import build_candidate_lineage
        from retrieval_observatory.tracing.lineage_diff import diff_candidate_lineage

        _reject_policy_path(policy_path)
        store = _store_for(db_id)
        baseline_db_id = against_db_id or db_id
        baseline_store = _store_for(baseline_db_id)
        candidate_traces = await store.list_traces(
            TraceQuery(run_id=run_id, query_id=query_id)
        )
        baseline_traces = await baseline_store.list_traces(
            TraceQuery(run_id=against, query_id=query_id)
        )
        if not candidate_traces or not baseline_traces:
            raise HTTPException(
                status_code=404,
                detail="Both selected runs must contain traces for the paired query.",
            )

        baseline_manifest = await baseline_store.get_run_manifest(against) or {}
        candidate_manifest = await store.get_run_manifest(run_id) or {}
        try:
            policy = load_release_policy(policy_path) if policy_path else None
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid local release policy: {exc}",
            ) from exc
        readiness = assess_evidence(
            policy, baseline_manifest, candidate_manifest
        ).readiness["lineage_diff"]
        baseline_qrels = (await _resolve_qrels(baseline_store, against)).get(query_id, {})
        candidate_qrels = (await _resolve_qrels(store, run_id)).get(query_id, {})

        def mapping_complete(manifest: Dict[str, Any]) -> bool:
            return (
                ((manifest.get("evidence_profile") or {}).get("lineage") or {}).get(
                    "qrel_to_chunk_mapping_coverage"
                )
                == 1.0
            )

        baseline_by_pipeline: Dict[str, List[RetrievalTrace]] = defaultdict(list)
        candidate_by_pipeline: Dict[str, List[RetrievalTrace]] = defaultdict(list)
        for trace in baseline_traces:
            baseline_by_pipeline[trace.pipeline_id].append(trace)
        for trace in candidate_traces:
            candidate_by_pipeline[trace.pipeline_id].append(trace)

        trace_pairs: list[tuple[RetrievalTrace, RetrievalTrace]] = []
        unpaired_baseline: list[RetrievalTrace] = []
        unpaired_candidate: list[RetrievalTrace] = []
        pairing_reasons: list[str] = []
        for pipeline_id in sorted(
            baseline_by_pipeline.keys() | candidate_by_pipeline.keys()
        ):
            baseline_items = baseline_by_pipeline[pipeline_id]
            candidate_items = candidate_by_pipeline[pipeline_id]
            if len(baseline_items) == len(candidate_items) == 1:
                trace_pairs.append((baseline_items[0], candidate_items[0]))
                continue
            baseline_requests = {
                trace.request_id: trace for trace in baseline_items if trace.request_id
            }
            candidate_requests = {
                trace.request_id: trace for trace in candidate_items if trace.request_id
            }
            request_pairing_is_complete = (
                len(baseline_requests) == len(baseline_items)
                and len(candidate_requests) == len(candidate_items)
                and baseline_requests.keys() == candidate_requests.keys()
            )
            if request_pairing_is_complete:
                trace_pairs.extend(
                    (baseline_requests[request_id], candidate_requests[request_id])
                    for request_id in sorted(baseline_requests)
                )
                continue
            unpaired_baseline.extend(baseline_items)
            unpaired_candidate.extend(candidate_items)
            pairing_reasons.append(
                f"Pipeline {pipeline_id} has ambiguous trace instances; record a unique shared request_id for cross-run pairing."
            )

        def graph_for(trace: RetrievalTrace, *, baseline: bool):
            manifest = baseline_manifest if baseline else candidate_manifest
            qrels = baseline_qrels if baseline else candidate_qrels
            return build_candidate_lineage(
                trace,
                qrels_for_query=qrels,
                qrel_chunk_mapping_complete=mapping_complete(manifest),
            )

        diffs = []
        for baseline_trace, candidate_trace in trace_pairs:
            baseline_graph = graph_for(baseline_trace, baseline=True)
            candidate_graph = graph_for(candidate_trace, baseline=False)
            diffs.append(
                asdict(
                    diff_candidate_lineage(
                        baseline_graph,
                        candidate_graph,
                        readiness=readiness,
                    )
                )
            )

        readiness_payload = readiness.model_dump(mode="json")
        blocked_reasons = [*pairing_reasons, *list(
            dict.fromkeys(
                reason
                for item in diffs
                if item["status"] == "BLOCK" and readiness.status != "BLOCK"
                for reason in item["reasons"]
            )
        )]
        if blocked_reasons:
            readiness_payload = {
                **readiness_payload,
                "status": "BLOCK",
                "findings": [
                    *readiness_payload["findings"],
                    {
                        "code": "lineage_candidate_identity_unaligned",
                        "scope": "lineage_diff",
                        "status": "BLOCK",
                        "observed": blocked_reasons,
                        "required": (
                            "matching query, pipeline, logical chunk, document revision/content hash, "
                            "and topology identity"
                        ),
                        "detail": "Candidate paths cannot be aligned for a stage-level diff.",
                        "next_action": "Inspect the recorded paths side by side without attributing cause.",
                    },
                ],
            }

        return {
            "baseline_run_id": against,
            "baseline_db_id": baseline_db_id,
            "candidate_run_id": run_id,
            "candidate_db_id": db_id,
            "query_id": query_id,
            "readiness": readiness_payload,
            "diffs": diffs,
            "unpaired": {
                "baseline": [asdict(graph_for(trace, baseline=True)) for trace in unpaired_baseline],
                "candidate": [asdict(graph_for(trace, baseline=False)) for trace in unpaired_candidate],
            },
        }

    @db_router.get("/runs/{run_id}/queries/{query_id}/lineage-accounting")
    async def get_lineage_accounting(db_id: str, run_id: str, query_id: str) -> Dict[str, Any]:
        payload = await _query_lineage_payload(db_id, run_id, query_id)
        return {
            "run_id": run_id,
            "query_id": query_id,
            "readiness": payload["readiness"],
            "evidence_warnings": payload["evidence_warnings"],
            "accounting": payload["accounting"],
            "traces": [
                {
                    "trace_id": item["trace_id"],
                    "pipeline_id": item["pipeline_id"],
                    "accounting": item["accounting"],
                }
                for item in payload["traces"]
            ],
        }

    @db_router.get("/runs/{run_id}/queries/{query_id}/candidate-journeys")
    async def get_candidate_journeys(
        db_id: str, run_id: str, query_id: str, k: int = 10,
    ) -> Dict[str, Any]:
        """Miss-overview rows for one query: relevant docs + docs dropped mid-pipeline.

        Joins qrels, candidate_history, and miss attribution so the Query-detail table
        does not N+1 the per-doc flow endpoint.
        """
        if not 1 <= k <= 100:
            raise HTTPException(status_code=422, detail="k must be 1..100")
        from retrieval_observatory.tracing.candidate_journeys import build_candidate_journeys

        store = _store_for(db_id)
        query_traces = await store.list_traces(TraceQuery(run_id=run_id, query_id=query_id))
        if not query_traces:
            raise HTTPException(
                status_code=404,
                detail=f"No traces for query '{query_id}' in run '{run_id}' (candidate journeys need trace data)",
            )
        qrels = await _resolve_qrels(store, run_id)
        qrels_for_query = qrels.get(query_id, {})
        manifest = await store.get_run_manifest(run_id) or {}
        mapping_coverage = (
            ((manifest.get("evidence_profile") or {}).get("lineage") or {}).get(
                "qrel_to_chunk_mapping_coverage"
            )
        )
        query_text = query_traces[0].query_text
        if hasattr(store, "get_run_queries"):
            for row in await store.get_run_queries(run_id):
                if row.get("query_id") == query_id and row.get("query_text"):
                    query_text = row["query_text"]
                    break
        rows = await build_candidate_journeys(
            query_traces,
            query_id=query_id,
            query_text=query_text,
            qrels_for_query=qrels_for_query,
            k=k,
            qrel_chunk_mapping_complete=mapping_coverage == 1.0,
        )
        return {
            "run_id": run_id,
            "query_id": query_id,
            "query_text": query_text,
            "k": k,
            "rows": rows,
        }

    @db_router.get("/runs/{run_id}/stage-matrix")
    async def get_stage_matrix(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        agg = await _aggregate(db_id, run_id, store)
        run_rows = [run for run in await store.list_runs() if run["run_id"] == run_id]
        config = json.loads(run_rows[0]["config_json"]) if run_rows else {}
        costs = config.get("costs", {})
        cells = []
        for key, value in agg.items():
            if value["stage_index"] < 0:
                continue
            cells.append({"metric": key, "estimated_cost_per_1k": _pipeline_cost_per_1k(config, value["pipeline_id"], costs), **value})
        return {"run_id": run_id, "cells": cells}

    @db_router.post("/runs/{run_id}/traces")
    async def ingest_trace(db_id: str, run_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        store = _store_for(db_id)
        trace = _parse_trace(payload, run_id=run_id)
        await store.save_trace(trace)
        return {"trace_id": trace.trace_id, "stored": True}

    @db_router.get("/runs/{run_id}/traces")
    async def list_run_traces(
        db_id: str,
        run_id: str,
        query_id: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        store = _store_for(db_id)
        if limit < 1 or limit > 500 or offset < 0:
            raise HTTPException(status_code=422, detail="limit must be 1..500 and offset must be non-negative")
        traces = await store.list_traces(TraceQuery(run_id=run_id, query_id=query_id, limit=limit, offset=offset))
        return [trace.to_dict() for trace in traces]

    @db_router.get("/runs/{run_id}/queries/{query_id}/evidence")
    async def get_query_evidence(
        db_id: str,
        run_id: str,
        query_id: str,
        trace_limit: int = 20,
        trace_offset: int = 0,
        candidate_limit: int = 100,
    ) -> Dict[str, Any]:
        if not 1 <= trace_limit <= 100:
            raise HTTPException(status_code=422, detail="trace_limit must be 1..100")
        if trace_offset < 0 or not 1 <= candidate_limit <= 1000:
            raise HTTPException(status_code=422, detail="trace_offset must be non-negative and candidate_limit must be 1..1000")
        from retrieval_observatory.evidence.query import build_query_evidence

        try:
            return await build_query_evidence(
                _store_for(db_id),
                db_id=db_id,
                run_id=run_id,
                query_id=query_id,
                trace_limit=trace_limit,
                trace_offset=trace_offset,
                candidate_limit=candidate_limit,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error))

    @db_router.get("/runs/{run_id}/traces/{trace_id}")
    async def get_run_trace(db_id: str, run_id: str, trace_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        trace = await store.get_trace(trace_id)
        if trace is None or trace.run_id != run_id:
            raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found for run '{run_id}'")
        return trace.to_dict()

    @db_router.get("/runs/{run_id}/pipeline-graph")
    async def get_pipeline_graph(db_id: str, run_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Canonical PipelineGraph projection (nodes + edges, every metric with its CI or null)
        built from persisted traces + aggregated metrics. Drives the dashboard DAG view, the
        offline HTML diagram, and the MCP get_pipeline_diagram tool from one contract."""
        from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs

        store = _store_for(db_id)
        agg = await _aggregate(db_id, run_id, store)
        traces = await store.list_traces(TraceQuery(run_id=run_id))
        graphs = build_pipeline_graphs(
            agg,
            traces,
            projection_mode="trace" if trace_id else "run_union",
            trace_id=trace_id,
        )
        if trace_id and not graphs:
            raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found in run '{run_id}'")
        return {"run_id": run_id, "pipelines": [g.to_dict() for g in graphs]}

    @db_router.get("/runs/{run_id}/operator-dag")
    async def get_operator_dag(db_id: str, run_id: str) -> Dict[str, Any]:
        """Compatibility view derived only from the canonical PipelineGraphV2 contract."""
        graph_response = await get_pipeline_graph(db_id, run_id)
        pipelines = graph_response["pipelines"]
        if not pipelines:
            raise HTTPException(status_code=404, detail=f"No traces for run '{run_id}'")
        return _operator_dag_from_pipelines(pipelines)

    @db_router.post("/edges")
    async def add_edge(db_id: str, edge: EdgeRequest) -> Dict[str, Any]:
        store = _store_for(db_id)
        await store.save_doc_edge(edge.src_doc_id, edge.dst_doc_id, edge.edge_type, edge.weight)
        return {"stored": True}

    @db_router.post("/edges/batch")
    async def add_edges_batch(db_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        store = _store_for(db_id)
        edges = payload.get("edges", [])
        for e in edges:
            await store.save_doc_edge(e["src_doc_id"], e["dst_doc_id"], e["edge_type"], float(e.get("weight", 1.0)))
        return {"stored": len(edges)}

    @db_router.get("/edges/{doc_id}")
    async def get_neighbors(db_id: str, doc_id: str, edge_type: str = "") -> List[Dict[str, Any]]:
        store = _store_for(db_id)
        return await store.get_doc_neighbors(doc_id, edge_type=edge_type or None)

    @db_router.get("/runs/{run_id}/query-winners")
    async def get_query_winners(db_id: str, run_id: str, metric: str = "recall", k: int = 10) -> Dict[str, Any]:
        _bound("k", k, 1, 1000)
        store = _store_for(db_id)
        rows = await store.get_metrics(run_id)
        scored: Dict[str, Dict[str, tuple[int, float]]] = defaultdict(dict)
        for row in rows:
            if row.get("metric_name") != metric or int(row.get("k", 0)) != k or row.get("branch_id"):
                continue
            stage = int(row.get("stage_index", -1))
            pid = row.get("pipeline_id")
            qid = row.get("query_id")
            current = scored[qid].get(pid)
            if current is None:
                scored[qid][pid] = (stage, float(row["value"]))  # type: ignore[assignment]
            elif stage >= current[0]:
                scored[qid][pid] = (stage, float(row["value"]))  # type: ignore[assignment]
        winners = []
        for qid, values in scored.items():
            if not values:
                winners.append({"query_id": qid, "winner_pipeline_id": None, "status": "not_judged"})
                continue
            best = max(values.items(), key=lambda item: item[1][1])
            winners.append(
                {
                    "query_id": qid,
                    "winner_pipeline_id": best[0],
                    "score": best[1][1],
                    "status": "measured",
                }
            )
        return {"run_id": run_id, "metric": metric, "k": k, "items": winners}

    def _register_upload_unavailable() -> None:
        @app.post("/validate")
        async def validate_upload_unavailable() -> Dict[str, Any]:
            raise HTTPException(
                status_code=501,
                detail="Install retrieval-observatory[dashboard] with python-multipart to use upload validation.",
            )

        @app.post("/experiments/prepare")
        async def prepare_upload_unavailable() -> Dict[str, Any]:
            raise HTTPException(
                status_code=501,
                detail="Install retrieval-observatory[dashboard] with python-multipart to use experiment uploads.",
            )

    if enable_uploads:
        try:
            import multipart  # noqa: F401

            @app.post("/validate")
            async def validate_uploaded_config(config_file: UploadFile = File(...)) -> Dict[str, Any]:
                from retrieval_observatory.config.schema import ExperimentConfig
                from retrieval_observatory.datasets.validation import validate_experiment_config
                import yaml

                content = await config_file.read()
                cfg = ExperimentConfig.model_validate(yaml.safe_load(content))
                report = validate_experiment_config(cfg, config_file.filename)
                await default_store.save_validation_report(report, config_path=config_file.filename)
                return report

            @app.post("/experiments/prepare")
            async def prepare_experiment(
                config_file: UploadFile = File(...),
                queries_file: UploadFile | None = File(None),
                corpus_file: UploadFile | None = File(None),
                qrels_file: UploadFile | None = File(None),
            ) -> Dict[str, Any]:
                upload_id = str(uuid.uuid4())[:8]
                upload_dir = os.path.join(".retobs", "uploads", upload_id)
                os.makedirs(upload_dir, exist_ok=True)

                async def _save(upload: UploadFile | None, filename: str) -> str | None:
                    if upload is None:
                        return None
                    path = os.path.join(upload_dir, filename)
                    with open(path, "wb") as f:
                        shutil.copyfileobj(upload.file, f)
                    return path

                config_path = await _save(config_file, "experiment.yaml")
                queries_path = await _save(queries_file, "queries.jsonl")
                corpus_path = await _save(corpus_file, "corpus.jsonl")
                qrels_path = await _save(qrels_file, "qrels.jsonl")

                return {
                    "upload_id": upload_id,
                    "config_path": config_path,
                    "queries_path": queries_path,
                    "corpus_path": corpus_path,
                    "qrels_path": qrels_path,
                    "run_command": f"retobs run --config {config_path}",
                }
        except Exception:
            _register_upload_unavailable()
    else:
        _register_upload_unavailable()

    app.include_router(db_router)

    def _evidence_store(db_id: str = ""):
        if db_id:
            return _store_for(db_id)
        if not registry.is_single:
            raise HTTPException(status_code=400, detail="Explicit db_id scope is required when multiple databases are loaded")
        return _store_for(registry.default_db_id or "")

    from retrieval_observatory.dashboard.analysis_api import build_analysis_router
    app.include_router(build_analysis_router(_store_for))
    from retrieval_observatory.dashboard.investigation_api import build_investigation_router
    app.include_router(build_investigation_router(registry))
    from retrieval_observatory.dashboard.integration_api import build_integration_router
    app.include_router(build_integration_router(registry))

    @app.get("/dbs/{db_id}/query/{query_id}/lineage")
    @app.get("/query/{query_id}/lineage")
    async def get_query_lineage(query_id: str, db_id: str = "") -> Dict[str, Any]:
        store = _evidence_store(db_id)
        if not store or not hasattr(store, "get_query_lineage"):
            raise HTTPException(status_code=404, detail="Lineage not available")
        return await store.get_query_lineage(query_id)

    production_router = APIRouter(prefix="/production")

    def _production_store(db_id: str = ""):
        return _evidence_store(db_id)

    def _parse_trace(payload: Dict[str, Any], *, run_id: str | None = None) -> RetrievalTrace:
        data = dict(payload)
        if data.get("schema_version", 1) != 1:
            raise HTTPException(status_code=422, detail="schema_version must be 1")
        data.setdefault("run_id", run_id)
        return RetrievalTrace.from_dict(data)

    @app.post("/dbs/{db_id}/production/traces")
    @production_router.post("/traces")
    async def ingest_traces(payload: Any = Body(...), db_id: str = "") -> Dict[str, Any]:
        """Ingest one trace (object) or many (list). Enriches server-side, then stores."""
        store = _production_store(db_id)
        if not store:
            raise HTTPException(status_code=503, detail="No store available for trace ingestion")
        items = payload if isinstance(payload, list) else [payload]
        traces = []
        for item in items:
            traces.append(_parse_trace(item))
        await store.save_traces(traces)
        return {"ingested": len(traces)}

    @app.get("/dbs/{db_id}/production/services")
    @production_router.get("/services")
    async def list_trace_services(db_id: str = "") -> List[Dict[str, Any]]:
        store = _production_store(db_id)
        if store and hasattr(store, "list_services"):
            return [
                {**_dataclass_asdict(summary), "service": summary.service_id}
                for summary in await store.list_services()
            ]
        return []

    @app.get("/dbs/{db_id}/production/services/{service_id}/instrumentation-health")
    @production_router.get("/services/{service_id}/instrumentation-health")
    async def instrumentation_health(service_id: str, db_id: str = "") -> Dict[str, Any]:
        store = _production_store(db_id)
        snapshot = await store.get_instrumentation_health(service_id)
        if snapshot is None:
            return {
                "service_id": service_id,
                "evidence_class": "unavailable",
                "method_version": "instrumentation-health/1",
                "sample_size": 0,
                "limitations": [],
                "unavailable_reason": "no instrumentation health snapshot",
            }
        payload = _dataclass_asdict(snapshot)
        payload.update({
            "evidence_class": "measured",
            "method_version": "instrumentation-health/1",
            "sample_size": snapshot.accepted,
            "limitations": ["sampled capture"] if snapshot.sample_rate < 1 else [],
            "unavailable_reason": None,
        })
        return payload

    @app.get("/dbs/{db_id}/production/traces")
    @production_router.get("/traces")
    async def list_traces_ep(
        service_id: str,
        since: str = "",
        until: str = "",
        status: str = "",
        difficulty: str = "",
        suspected_only: bool = False,
        limit: int = 200,
        offset: int = 0,
        db_id: str = "",
    ) -> Dict[str, Any]:
        _bound("limit", limit, 1, 500)
        _bound("offset", offset, 0, 1_000_000)
        store = _production_store(db_id)
        if store and hasattr(store, "list_traces"):
            matches = await store.list_traces(
                TraceQuery(
                    service_id=service_id,
                    since=_iso_or_422("since", since),
                    until=_iso_or_422("until", until),
                    status=status or None,
                )
            )
            # difficulty / suspected_only live in trace metadata, so they filter in Python
            # over the window; total reflects the filtered count.
            if difficulty:
                matches = [t for t in matches if t.metadata.get("predicted_difficulty") == difficulty]
            if suspected_only:
                matches = [t for t in matches if t.metadata.get("suspected_failures")]
            total = len(matches)
            page = matches[offset:offset + limit]
            return {
                "items": [_monitor_trace(trace) for trace in page],
                "total": total,
                "limit": limit,
                "offset": offset,
                "next_offset": offset + len(page) if offset + len(page) < total else None,
            }
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "next_offset": None}

    @app.get("/dbs/{db_id}/production/topology-variants")
    @production_router.get("/topology-variants")
    async def topology_variants(service_id: str, limit: int = 50, offset: int = 0, db_id: str = "") -> Dict[str, Any]:
        _bound("limit", limit, 1, 500)
        _bound("offset", offset, 0, 1_000_000)
        store = _production_store(db_id)
        variants = await store.list_topology_variants(TraceQuery(service_id=service_id, limit=100000))
        page = variants[offset:offset + limit]
        return {"items": [_dataclass_asdict(item) for item in page], "total": len(variants), "limit": limit, "offset": offset, "next_offset": offset + len(page) if offset + len(page) < len(variants) else None}

    @app.get("/dbs/{db_id}/production/traces/{trace_id}")
    @production_router.get("/traces/{trace_id}")
    async def get_trace_ep(trace_id: str, db_id: str = "") -> Dict[str, Any]:
        store = _production_store(db_id)
        if store and hasattr(store, "get_trace"):
            t = await store.get_trace(trace_id)
            if t:
                return _monitor_trace(t)
        raise HTTPException(status_code=404, detail=f"Trace {trace_id!r} not found")

    app.include_router(production_router)

    def _retired_endpoint(replacement: str, message: str):
        async def retired() -> None:
            raise HTTPException(
                status_code=410, detail={"code": "retired", "detail": message, "replacement": f"#/{replacement}"}
            )

        return retired

    # Registered before the SPA fallback so a retired GET never falls through to index.html.
    for _path, _replacement, _message in _RETIRED_ROUTES:
        app.add_api_route(
            _path, _retired_endpoint(_replacement, _message), methods=["GET", "POST"], include_in_schema=False
        )

    # Backward-compatible aliases when a single database is loaded.
    if registry.is_single:
        _sole_db = registry.default_db_id

        @app.get("/runs")
        async def legacy_list_runs() -> List[Dict]:
            return await registry.list_runs(_sole_db)

        @app.get("/runs/{run_id}/metrics")
        async def legacy_run_metrics(run_id: str) -> Dict[str, Any]:
            return await get_run_metrics(_sole_db, run_id)

        @app.get("/runs/{run_id}/metrics/by-segment")
        async def legacy_run_metrics_by_segment(run_id: str, field: str = "n_relevant") -> Dict[str, Any]:
            return await get_run_metrics_by_segment(_sole_db, run_id, field)

        @app.get("/runs/{run_id}/manifest")
        async def legacy_manifest(run_id: str) -> Dict[str, Any]:
            return await get_manifest(_sole_db, run_id)

        @app.get("/runs/{run_id}/diagnostics")
        async def legacy_diagnostics(run_id: str) -> Dict[str, Any]:
            return await get_diagnostics(_sole_db, run_id)

        @app.get("/runs/{run_id}/overview")
        async def legacy_overview(run_id: str) -> Dict[str, Any]:
            return await get_run_overview(_sole_db, run_id)

        @app.get("/runs/{run_id}/queries/{query_id}")
        async def legacy_query_result(run_id: str, query_id: str) -> Dict[str, Any]:
            return await get_query_result(_sole_db, run_id, query_id)

        @app.get("/runs/{run_id}/stage-matrix")
        async def legacy_stage_matrix(run_id: str) -> Dict[str, Any]:
            return await get_stage_matrix(_sole_db, run_id)

        @app.post("/runs/{run_id}/traces")
        async def legacy_ingest_trace(run_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
            return await ingest_trace(_sole_db, run_id, payload)

        @app.get("/runs/{run_id}/traces")
        async def legacy_list_traces(run_id: str) -> List[Dict[str, Any]]:
            return await list_run_traces(_sole_db, run_id)

        @app.get("/runs/{run_id}/traces/{trace_id}")
        async def legacy_get_trace(run_id: str, trace_id: str) -> Dict[str, Any]:
            return await get_run_trace(_sole_db, run_id, trace_id)

        @app.get("/runs/{run_id}/query-winners")
        async def legacy_query_winners(run_id: str, metric: str = "recall", k: int = 10) -> Dict[str, Any]:
            return await get_query_winners(_sole_db, run_id, metric, k)

    # ─────────────────────── Agent API: trigger + diagram ───────────────────────
    # Net-new endpoints for agent/programmatic use: trigger benchmark runs from a config
    # (not live Python objects — see run_from_config), poll status, compare two configs, and
    # fetch diagram-ready pipeline JSON with per-stage metrics + bootstrap CIs.
    runs_router = APIRouter(prefix="/dbs/{db_id}")

    def _config_for_db(db_id: str, config_body: Dict[str, Any]):
        from retrieval_observatory.config.schema import ExperimentConfig

        try:
            source = registry.get(db_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown database '{db_id}'")
        try:
            cfg = ExperimentConfig.model_validate(config_body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid experiment config: {e}")
        if source.path.startswith("postgres://") or source.path.startswith("postgresql://"):
            cfg.output.store = "postgres"
            cfg.output.postgres_dsn = source.path
        else:
            cfg.output.store = "sqlite"
            cfg.output.db_path = source.path
        return cfg

    async def _execute_config_run(
        cfg,
        run_id: str,
        max_queries: int | None,
        config_base_dir: str | None = None,
    ) -> Dict[str, Any]:
        from retrieval_observatory.sdk.run_config import _run_from_config_async

        _jobs[run_id] = {"run_id": run_id, "status": "running", "error": None}
        try:
            report = await _run_from_config_async(
                config=cfg,
                db_path=None,
                max_queries=max_queries,
                run_id=run_id,
                no_cache=False,
                config_base_dir=config_base_dir,
            )
            _jobs[run_id]["status"] = "completed"
            return report.metrics
        except Exception as e:  # noqa: BLE001 — surface the failure via job status
            _jobs[run_id]["status"] = "error"
            _jobs[run_id]["error"] = str(e)
            raise

    @runs_router.post("/runs", dependencies=[Depends(_require_auth)])
    async def trigger_run(
        db_id: str,
        payload: Dict[str, Any] = Body(...),
    ) -> Dict[str, Any]:
        """Trigger a benchmark run from an ExperimentConfig JSON.

        Body: {"config": <ExperimentConfig>, "wait"?: bool, "max_queries"?: int,
        "config_base_dir"?: str}. Default is a background job returning {run_id, status:"running"};
        poll GET .../status then read the existing metric endpoints. wait=true runs
        bounded-synchronously (use with max_queries). config_base_dir resolves relative dataset
        paths and adapter.import factories (same as retobs run --config).
        """
        config_body = payload.get("config")
        if not isinstance(config_body, dict):
            raise HTTPException(status_code=422, detail="Body must include a 'config' object")
        wait = bool(payload.get("wait", False))
        max_queries = payload.get("max_queries")
        config_base_dir = payload.get("config_base_dir")
        cfg = _config_for_db(db_id, config_body)
        run_id = str(uuid.uuid4())[:8]

        if _active_run_count() >= _max_concurrent_runs:
            raise HTTPException(
                status_code=429,
                detail=f"Too many concurrent runs (max {_max_concurrent_runs}); retry shortly.",
            )

        if wait:
            metrics = await _execute_config_run(cfg, run_id, max_queries, config_base_dir)
            return {"run_id": run_id, "status": "completed", "metrics": metrics}

        import asyncio

        _jobs[run_id] = {"run_id": run_id, "status": "running", "error": None}
        asyncio.create_task(_execute_config_run(cfg, run_id, max_queries, config_base_dir))
        return {"run_id": run_id, "status": "running"}

    @runs_router.get("/runs/{run_id}/status")
    async def run_status(db_id: str, run_id: str) -> Dict[str, Any]:
        """Poll a triggered run. Falls back to the persisted runs table for completed runs."""
        job = _jobs.get(run_id)
        if job:
            return job
        store = _store_for(db_id)
        rows = [r for r in await store.list_runs() if r["run_id"] == run_id]
        if not rows:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        row = rows[0]
        status = "completed" if row.get("finished_at") else "running"
        return {"run_id": run_id, "status": status, "error": None,
                "started_at": row.get("started_at"), "finished_at": row.get("finished_at")}

    @runs_router.post("/compare-configs", dependencies=[Depends(_require_auth)])
    async def compare_configs(db_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Run a baseline and candidate config, then return a paired comparison.

        Body: {"baseline_config": {...}, "candidate_config": {...}, "max_queries"?: int,
        "config_base_dir"?: str}.
        This is the agent 'benchmark this config against a baseline' primitive.
        """
        baseline_body = payload.get("baseline_config")
        candidate_body = payload.get("candidate_config")
        if not isinstance(baseline_body, dict) or not isinstance(candidate_body, dict):
            raise HTTPException(status_code=422, detail="Provide baseline_config and candidate_config")
        max_queries = payload.get("max_queries")
        config_base_dir = payload.get("config_base_dir")
        if _active_run_count() >= _max_concurrent_runs:
            raise HTTPException(status_code=429, detail="Too many concurrent runs; retry shortly.")

        baseline_cfg = _config_for_db(db_id, baseline_body)
        candidate_cfg = _config_for_db(db_id, candidate_body)
        baseline_run_id = str(uuid.uuid4())[:8]
        candidate_run_id = str(uuid.uuid4())[:8]
        await _execute_config_run(baseline_cfg, baseline_run_id, max_queries, config_base_dir)
        await _execute_config_run(candidate_cfg, candidate_run_id, max_queries, config_base_dir)

        result = await _build_comparison(
            [(db_id, baseline_run_id), (db_id, candidate_run_id)], registry, engine,
            aggregate_cache=aggregate_cache,
        )
        significant = any(
            entry.get("p_value") is not None and entry["p_value"] < 0.05
            for entry in result["comparison"]
        )
        return {
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "comparison": result["comparison"],
            "warnings": result["warnings"],
            "significant": significant,
        }

    @runs_router.get("/runs/{run_id}/diagram")
    async def get_run_diagram(db_id: str, run_id: str) -> Dict[str, Any]:
        """Diagram-ready pipeline JSON: trace-native DAG nodes (PipelineGraph contract) with
        metrics + bootstrap CIs, plus operator-DAG fire-rate/latency. Consumed by the SPA and
        by the `retobs diagram` HTML export. Requires V2 traces -- a config-only run with no
        execution traces yet gets an honest 404, not a topology inferred from stage snapshots."""
        from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs

        store = _store_for(db_id)
        agg = await _aggregate(db_id, run_id, store)
        if not agg:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")
        traces = await store.list_traces(TraceQuery(run_id=run_id))
        if not traces:
            raise HTTPException(
                status_code=404,
                detail=f"Run '{run_id}' has no execution traces yet -- no diagram to render.",
            )
        pipelines = [g.to_dict() for g in build_pipeline_graphs(agg, traces)]
        return {
            "run_id": run_id,
            "pipelines": pipelines,
            "operator_dag": _operator_dag_from_pipelines(pipelines),
        }

    @app.get("/config/schema")
    async def config_schema_endpoint() -> Dict[str, Any]:
        """ExperimentConfig JSON schema + runnable example + per-adapter snippets. Lets an agent
        discover the config shape before triggering a run."""
        from retrieval_observatory.config.discovery import config_schema

        return config_schema()

    @app.post("/config/validate")
    async def validate_config_endpoint(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Dry-run validate a config ({"config": {...}}) without running a benchmark."""
        from retrieval_observatory.config.discovery import validate_config_dict

        config_body = payload.get("config", payload)
        if not isinstance(config_body, dict):
            raise HTTPException(status_code=422, detail="Body must include a 'config' object")
        return validate_config_dict(config_body)

    app.include_router(runs_router)

    # Serve React UI static files if built
    if os.path.exists(_UI_DIST):
        from starlette.staticfiles import StaticFiles as StarletteStaticFiles

        class _CachedStaticFiles(StarletteStaticFiles):
            async def get_response(self, path: str, scope):  # type: ignore[override]
                response = await super().get_response(path, scope)
                if response.status_code == 200:
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response

        assets_dir = os.path.join(_UI_DIST, "assets")
        if os.path.exists(assets_dir):
            app.mount("/assets", _CachedStaticFiles(directory=assets_dir), name="assets")

        _index = os.path.join(_UI_DIST, "index.html")

        @app.get("/", include_in_schema=False)
        async def spa_root():
            return _index_response(_index)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if _is_static_asset_path(full_path):
                raise HTTPException(status_code=404, detail="Not found")
            return _index_response(_index)

    return app


def _headline_winner(metrics: Dict[str, Any]) -> Dict[str, Any] | None:
    """Pick best final-stage NDCG@10 across pipelines (tie-break Recall@10)."""
    final_stage_by_pipeline: Dict[str, int] = {}
    for value in metrics.values():
        if value.get("branch_id"):
            continue
        pid = value.get("pipeline_id")
        sidx = value.get("stage_index", -1)
        if pid and sidx >= 0:
            final_stage_by_pipeline[pid] = max(final_stage_by_pipeline.get(pid, -1), sidx)

    candidates = [
        {"metric": key, **value}
        for key, value in metrics.items()
        if value.get("stage_index", -1) >= 0
        and not value.get("branch_id")
        and value.get("pipeline_id") in final_stage_by_pipeline
        and value.get("stage_index") == final_stage_by_pipeline[value.get("pipeline_id")]
        and value.get("metric_name") in {"ndcg", "recall"}
        and value.get("k") in {10, 20}
    ]
    if not candidates:
        return None

    ndcg10 = [c for c in candidates if c.get("metric_name") == "ndcg" and c.get("k") == 10]
    if ndcg10:
        best_ndcg = max(ndcg10, key=lambda row: row.get("mean", 0.0))
        best_mean = best_ndcg.get("mean", 0.0)
        tied = [c for c in ndcg10 if abs(c.get("mean", 0.0) - best_mean) < 1e-9]
        if len(tied) == 1:
            return best_ndcg
        recall10 = {
            c["pipeline_id"]: next(
                (r.get("mean", 0.0) for r in candidates
                 if r.get("pipeline_id") == c["pipeline_id"]
                 and r.get("metric_name") == "recall" and r.get("k") == 10),
                0.0,
            )
            for c in tied
        }
        return max(tied, key=lambda row: recall10.get(row.get("pipeline_id"), 0.0))

    return max(candidates, key=lambda row: row.get("mean", 0.0))


def _is_quality_metric_row(value: Dict[str, Any]) -> bool:
    if value.get("branch_id"):
        return False
    name = value.get("metric_name") or ""
    if name.startswith("latency") or name.startswith("profile_"):
        return False
    if name in ("failure_rate", "timeout_rate", "dropout_count"):
        return False
    return value.get("stage_index", 0) >= 0


def _headline_metric_label(metric_name: str, k: int) -> str | None:
    """Metrics we surface in run-level warnings (avoid profile/latency noise)."""
    if metric_name in ("ndcg", "recall", "mrr", "map"):
        return f"{metric_name}@{k}" if k else metric_name
    return None


def _overview_warnings(metrics: Dict[str, Any], diagnostics: List[Dict], manifest: Dict | None) -> List[str]:
    warnings = []
    if manifest:
        for w in manifest.get("run_warnings", []):
            warnings.append(w)
    if any(value.get("metric_name") == "failure_rate" and value.get("mean", 0.0) > 0 and not value.get("branch_id") for value in metrics.values()):
        warnings.append("At least one pipeline had failed or timed-out queries.")
    if any("qrel_not_in_corpus" in row.get("failure_labels", []) for row in diagnostics):
        warnings.append("Some positively judged document IDs are absent from the loaded corpus.")
    if any("corpus_identity_unknown" in row.get("failure_labels", []) for row in diagnostics):
        warnings.append("Corpus identity was unavailable, so qrel membership could not be verified.")
    if manifest and manifest.get("dataset", {}).get("missing_qrel_doc_ids", 0):
        warnings.append("Some qrel document IDs were missing from the loaded corpus.")
    if manifest and manifest.get("unjudged_query_count", 0):
        n = manifest["unjudged_query_count"]
        warnings.append(
            f"{n} quer{'y' if n == 1 else 'ies'} had no relevance judgments and were excluded "
            "from quality metric means. Metrics reflect only judged queries."
        )
    if manifest and manifest.get("cache_results"):
        warnings.append(
            "Result caching was enabled for this run (manifest: cache_results=true). "
            "Latency percentiles may be optimistic on re-runs; use --no-cache for cold-path timing."
        )
    zero_by_pipeline: Dict[str, List[str]] = defaultdict(list)
    ci_by_pipeline: Dict[str, List[str]] = defaultdict(list)
    for value in metrics.values():
        if not _is_quality_metric_row(value):
            continue
        mname = value.get("metric_name") or ""
        k = int(value.get("k") or 0)
        label = _headline_metric_label(mname, k)
        if label is None:
            continue
        pid = value.get("pipeline_id", "?")
        zero_pct = value.get("zero_pct") or 0.0
        if zero_pct > 20:
            zero_by_pipeline[pid].append(
                f"{label} {zero_pct:.1f}% ({value.get('zero_count', 0)}/{value.get('n', 0)} queries)"
            )
        if (value.get("n") or 0) < 30:
            continue
        mean = abs(value.get("mean") or 0.0)
        ci_low = value.get("ci_low")
        ci_high = value.get("ci_high")
        if ci_low is None or ci_high is None:
            continue
        ci_width = ci_high - ci_low
        rel_width = ci_width / max(mean, 0.001)
        if rel_width >= 0.35:
            ci_by_pipeline[pid].append(f"{label} (CI width {ci_width:.3f}, {rel_width * 100:.0f}% of mean)")
        elif ci_width >= 0.05 and mean < 0.2:
            ci_by_pipeline[pid].append(f"{label} (mean {mean:.3f}, CI width {ci_width:.3f})")

    for pid, parts in sorted(zero_by_pipeline.items()):
        warnings.append(
            f"{pid}: elevated zero-score rate — "
            + "; ".join(parts)
            + ". No relevant documents in top-K for those queries; means overstate typical performance."
        )
    for pid, parts in sorted(ci_by_pipeline.items()):
        warnings.append(
            f"{pid}: wide or sparse confidence intervals on "
            + "; ".join(parts)
            + ". Treat means as directional."
        )
    return warnings


def _compute_stage_contributions(
    metrics: Dict[str, Any],
    metrics_rows: List[Dict],
    parent_map: Dict[str, Dict[str, set]] | None = None,
) -> List[Dict]:
    """Return cross-pipeline, within-pipeline, and fused-arm ablation deltas.

    ``parent_map`` (pipeline_id -> op_id -> declared parent op_ids) lets arm-vs-fused rows pair
    each branch arm with the spine node it actually feeds. Without it, an arm at depth d is
    paired with the nearest spine depth > d, which is right for every simple fan-in.
    """
    pipeline_ids = sorted({v.get("pipeline_id") for v in metrics.values() if v.get("pipeline_id")})
    prefix_pairs = pipeline_pairs(pipeline_ids)

    keys_by_pipeline: Dict[str, Dict[int, List[tuple]]] = {}
    keys_by_pipeline_branch: Dict[str, Dict[int, Dict[str, List[tuple]]]] = {}
    for key in metrics:
        try:
            pid, sidx, mname, k, branch_id = parse_metric_key(key)
        except Exception:
            continue
        if branch_id:
            keys_by_pipeline_branch.setdefault(pid, {}).setdefault(sidx, {}).setdefault(branch_id, []).append((mname, k, key))
            continue
        keys_by_pipeline.setdefault(pid, {}).setdefault(sidx, []).append((mname, k, key))

    quality_metrics = {"recall", "ndcg", "mrr", "map"}
    contributions: List[Dict[str, Any]] = []

    # Index per-query scores once: (pipeline, stage, branch, metric, k) -> {query_id: value}.
    # _build_delta runs for every layer x metric, and scanning the full row list each time is
    # the dominant cost of /overview on runs with tens of thousands of metric rows.
    scores_index: Dict[tuple, Dict[str, float]] = defaultdict(dict)
    for row in metrics_rows:
        scores_index[(row["pipeline_id"], row["stage_index"], row.get("branch_id"), row["metric_name"], row["k"])][row["query_id"]] = row["value"]

    def _build_delta(
        before_id: str,
        before_stage: int,
        before_branch: str | None,
        after_id: str,
        after_stage: int,
        after_branch: str | None,
    ) -> tuple[Dict[str, Any], float | None, float | None, bool]:
        before_keys = (
            keys_by_pipeline_branch.get(before_id, {}).get(before_stage, {}).get(before_branch, [])
            if before_branch
            else keys_by_pipeline.get(before_id, {}).get(before_stage, [])
        )
        after_keys = (
            keys_by_pipeline_branch.get(after_id, {}).get(after_stage, {}).get(after_branch, [])
            if after_branch
            else keys_by_pipeline.get(after_id, {}).get(after_stage, [])
        )

        before_quality = {(mname, k): fk for mname, k, fk in before_keys if mname in quality_metrics}
        after_quality = {(mname, k): fk for mname, k, fk in after_keys if mname in quality_metrics}
        deltas: Dict[str, Any] = {}
        raw_p_values: List[float] = []
        delta_p_map: List[tuple] = []
        has_indeterminate = False
        for mk in sorted(set(before_quality) & set(after_quality)):
            mname, k = mk
            b_mean = metrics[before_quality[mk]]["mean"]
            a_mean = metrics[after_quality[mk]]["mean"]
            absolute = a_mean - b_mean
            pct = (absolute / b_mean * 100) if b_mean != 0 else 0.0

            b_scores = scores_index.get((before_id, before_stage, before_branch, mname, k), {})
            a_scores = scores_index.get((after_id, after_stage, after_branch, mname, k), {})
            shared = sorted(set(b_scores) & set(a_scores))
            p = None
            indeterminate = False
            indeterminate_reason = None
            # For arm-vs-fused comparisons, a fused branch can be "present" but contain
            # only zeros (e.g., failed retrieval on that query set). Treat this as
            # insufficient data instead of implying no arm benefit.
            if before_branch is not None and after_branch is None:
                arm_has_signal = any(v > 0 for v in b_scores.values())
                fused_has_signal = any(v > 0 for v in a_scores.values())
                if arm_has_signal and not fused_has_signal:
                    indeterminate = True
                    indeterminate_reason = "fused_stage_no_quality_signal"
                    has_indeterminate = True
            if shared:
                p = paired_bootstrap_test([b_scores[q] for q in shared], [a_scores[q] for q in shared])
                if not indeterminate:
                    raw_p_values.append(p)
            delta_p_map.append((mname, k, b_mean, a_mean, absolute, pct, p, indeterminate, indeterminate_reason))

        q_values = benjamini_hochberg(raw_p_values)
        q_idx = 0
        for mname, k, b_mean, a_mean, absolute, pct, p, indeterminate, indeterminate_reason in delta_p_map:
            label = f"{mname}@{k}" if k > 0 else mname
            q_value = None
            if p is not None and not indeterminate:
                q_value = q_values[q_idx]
                q_idx += 1
            deltas[label] = {
                "before": b_mean,
                "after": a_mean,
                "absolute": absolute,
                "pct": pct,
                "q_value": q_value,
                "significant": (q_value is not None and q_value < 0.05 and not indeterminate),
                "indeterminate": indeterminate,
                "indeterminate_reason": indeterminate_reason,
                "n_pairs": len(shared) if shared else 0,
            }

        def _lat(
            metric_pipeline_id: str,
            metric_stage: int,
            stage_keys: List[tuple],
            branch: str | None,
        ) -> float | None:
            for mname, k, fk in stage_keys:
                if mname == "latency_p50" and k == 0:
                    return metrics[fk]["mean"]
            rows = [
                value
                for (pipeline_id, stage_index, branch_id, metric_name, _k), scores in scores_index.items()
                if pipeline_id == metric_pipeline_id
                and stage_index == metric_stage
                and branch_id == branch
                and metric_name == "latency_ms"
                for value in scores.values()
            ]
            if rows:
                return _percentile(rows, 50)
            return None

        lat_before = _lat(before_id, before_stage, before_keys, before_branch)
        lat_after = _lat(after_id, after_stage, after_keys, after_branch)
        return deltas, lat_before, lat_after, has_indeterminate

    for before_id, after_id in prefix_pairs:
        before_stages = keys_by_pipeline.get(before_id, {})
        after_stages = keys_by_pipeline.get(after_id, {})
        if not before_stages or not after_stages:
            continue
        before_last = max(s for s in before_stages if s >= 0)
        after_last = max(s for s in after_stages if s >= 0)
        deltas, lat_before, lat_after, has_indeterminate = _build_delta(before_id, before_last, None, after_id, after_last, None)
        contributions.append(
            {
                "comparison_tier": "cross_pipeline_prefix",
                "from_pipeline": before_id,
                "to_pipeline": after_id,
                "deltas": deltas,
                "latency_p50_before_ms": lat_before,
                "latency_p50_after_ms": lat_after,
                "latency_delta_ms": (lat_after - lat_before) if lat_before is not None and lat_after is not None else None,
                "indeterminate": has_indeterminate,
            }
        )

    for pid, stages in keys_by_pipeline.items():
        ordered = sorted(s for s in stages if s >= 0)
        branch_depths = sorted(d for d in keys_by_pipeline_branch.get(pid, {}) if d >= 0)
        for before_stage, after_stage in zip(ordered, ordered[1:]):
            # Consecutive spine depths; a depth holding only parallel arms has no spine
            # row, so the layer's effect is reported across it and labelled honestly.
            via_branch_depths = [d for d in branch_depths if before_stage < d < after_stage]
            deltas, lat_before, lat_after, has_indeterminate = _build_delta(pid, before_stage, None, pid, after_stage, None)
            contributions.append(
                {
                    "comparison_tier": "within_pipeline_stage",
                    "from_pipeline": f"{pid}:stage{before_stage}",
                    "to_pipeline": f"{pid}:stage{after_stage}",
                    "pipeline_id": pid,
                    "via_branch_depths": via_branch_depths,
                    "spans_branch_layer": bool(via_branch_depths),
                    "deltas": deltas,
                    "latency_p50_before_ms": lat_before,
                    "latency_p50_after_ms": lat_after,
                    "latency_delta_ms": (lat_after - lat_before) if lat_before is not None and lat_after is not None else None,
                    "indeterminate": has_indeterminate,
                }
            )

    for pid, stages in keys_by_pipeline_branch.items():
        spine_depths = sorted(s for s in keys_by_pipeline.get(pid, {}) if s >= 0)
        for stage_index, branches in sorted(stages.items()):
            for branch_id in sorted(branches):
                pairing = _fuse_stage_for_arm(pid, stage_index, branch_id, spine_depths, parent_map)
                if pairing is None:
                    continue
                fuse_stage, pairing_basis = pairing
                deltas, lat_before, lat_after, has_indeterminate = _build_delta(pid, stage_index, branch_id, pid, fuse_stage, None)
                contributions.append(
                    {
                        "comparison_tier": "within_stage_arm",
                        "from_pipeline": f"{pid}:stage{stage_index}:{branch_id}",
                        "to_pipeline": f"{pid}:stage{fuse_stage}:fused",
                        "pipeline_id": pid,
                        "stage_index": stage_index,
                        "fuse_stage_index": fuse_stage,
                        "pairing_basis": pairing_basis,
                        "branch_id": branch_id,
                        "deltas": deltas,
                        "latency_p50_before_ms": lat_before,
                        "latency_p50_after_ms": lat_after,
                        "latency_delta_ms": (lat_after - lat_before) if lat_before is not None and lat_after is not None else None,
                        "indeterminate": has_indeterminate,
                    }
                )

    return contributions


def _union_depths(parents: Dict[str, Any]) -> Dict[str, int]:
    """Longest-path depth of every op over declared parent ids -- the same layout rule
    MetricsEngine.compute_from_traces uses, so depths line up with metric stage_index."""
    cache: Dict[str, int] = {}

    def depth(op_id: str, visiting: frozenset) -> int:
        if op_id in cache:
            return cache[op_id]
        if op_id in visiting:
            return 0
        known = [parent for parent in parents.get(op_id, ()) if parent in parents]
        value = 0 if not known else 1 + max(depth(parent, visiting | {op_id}) for parent in known)
        cache[op_id] = value
        return value

    return {op_id: depth(op_id, frozenset()) for op_id in parents}


def _fuse_stage_for_arm(
    pipeline_id: str,
    depth: int,
    branch_id: str,
    spine_depths: List[int],
    parent_map: Dict[str, Dict[str, set]] | None,
) -> tuple[int, str] | None:
    """Spine depth an arm should be ablated against: the shallowest spine node downstream of
    the arm (the fuse it feeds). Returns (stage_index, basis) or None when nothing is deeper."""
    deeper = [stage for stage in spine_depths if stage > depth]
    if not deeper:
        return None
    parents = (parent_map or {}).get(pipeline_id) or {}
    if branch_id not in parents:
        return deeper[0], "depth_order"
    depths = _union_depths(parents)
    ops_by_depth: Dict[int, List[str]] = defaultdict(list)
    for op_id, op_depth in depths.items():
        ops_by_depth[op_depth].append(op_id)
    children: Dict[str, set] = defaultdict(set)
    for op_id, op_parents in parents.items():
        for parent in op_parents:
            children[parent].add(op_id)
    reachable: set = set()
    stack = [branch_id]
    while stack:
        current = stack.pop()
        for child in children.get(current, ()):
            if child not in reachable:
                reachable.add(child)
                stack.append(child)
    for stage in deeper:
        ops = ops_by_depth.get(stage, [])
        if len(ops) == 1 and ops[0] in reachable:
            return stage, "topology"
    return deeper[0], "depth_order"


async def _pipeline_parent_map(store: Any, run_id: str, metrics: Dict[str, Any], sample: int = 25) -> Dict[str, Dict[str, set]]:
    """Declared parent ids per op for every pipeline that has branch metrics, from a bounded
    trace sample (topology is declared per span, so a handful of traces is enough)."""
    branched = sorted({v.get("pipeline_id") for v in metrics.values() if v.get("branch_id") and v.get("pipeline_id")})
    out: Dict[str, Dict[str, set]] = {}
    for pipeline_id in branched:
        try:
            traces = await store.list_traces(TraceQuery(run_id=run_id, pipeline_id=pipeline_id, limit=sample))
        except Exception:
            continue
        parents: Dict[str, set] = {}
        for trace in traces:
            for span in trace.spans:
                parents.setdefault(span.op_id, set()).update(span.parent_ids)
        if parents:
            out[pipeline_id] = parents
    return out


def _operator_dag_from_pipelines(pipelines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compatibility operator-DAG view derived from already-built PipelineGraph dicts."""
    nodes = [
        {
            "op_id": node["node_id"],
            "op_type": node["op_type"],
            "op_name": node["label"],
            "fire_rate": node["fire_rate"],
            "avg_latency_ms": node["latency"]["mean_ms"],
        }
        for pipeline in pipelines
        for node in pipeline["nodes"]
    ]
    edges = [
        {"source": edge["source"], "target": edge["target"]}
        for pipeline in pipelines
        for edge in pipeline["edges"]
    ]
    return {"nodes": nodes, "edges": edges}


def _pipeline_cost_per_1k(config: Dict[str, Any], pipeline_id: str, costs: Dict[str, Dict[str, float]]) -> float:
    from retrieval_observatory.config.cost import pipeline_cost_per_1k

    return pipeline_cost_per_1k(config, pipeline_id, costs)
