from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from retrieval_observatory.metrics.pareto import ParetoPipelineInput, compute_pareto_frontier
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.comparison import (
    _scores_for,
    compare_paired_metrics,
    comparison_validity,
    pipeline_pairs,
    parse_metric_key,
)
from retrieval_observatory.metrics.diagnostics import aggregate_diagnostics
from retrieval_observatory.metrics.significance import benjamini_hochberg, bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.tracing.attribution import operator_marginal_contribution
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.types import Document, StageSnapshot
from retrieval_observatory.config.diff import diff_configs
from retrieval_observatory.config.schema import ExperimentConfig
from dataclasses import asdict as _dataclass_asdict

_UI_DIST = os.path.join(os.path.dirname(__file__), "ui", "dist")
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

    class RunSelection(_BaseModel):
        db_id: str
        run_id: str
        role: Optional[Literal["baseline", "candidate", "reference"]] = None

    class MultiCompareRequest(_BaseModel):
        selections: List[RunSelection]

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


def _monitor_trace(trace: RetrievalTrace) -> Dict[str, Any]:
    payload = trace.to_dict()
    payload["total_latency_ms"] = trace.timing.wall_clock_ms
    payload.setdefault("predicted_difficulty", trace.metadata.get("predicted_difficulty"))
    payload.setdefault("suspected_failures", trace.metadata.get("suspected_failures", []))
    return payload


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
    rows = [
        {"query_id": qid, "a": scores_a[qid], "b": scores_b[qid], "delta": scores_a[qid] - scores_b[qid]}
        for qid in common
    ]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {"metric": metric_key, "run_a": run_a, "run_b": run_b, "rows": rows[:50]}


async def _build_comparison(
    selections: List[tuple],
    registry: DbRegistry,
    engine: MetricsEngine,
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
        aggregated[key] = await engine.aggregate(run_id, store)
        metric_rows[key] = await store.get_metrics(run_id)

    all_metric_keys = sorted(set().union(*(agg.keys() for agg in aggregated.values())))
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
    release_decision = None
    if len(selections) == 2:
        from retrieval_observatory.release.assessment import assess_evidence
        from retrieval_observatory.release.decision import decide_release

        assessment = assess_evidence(None, manifests[0] or {}, manifests[1] or {})
        decision = decide_release(None, assessment, [], [])
        candidate_run_id = selections[1][1]
        baseline_run_id = selections[0][1]
        affected_query_ids = [row["query_id"] for row in (query_diffs or {}).get("rows", [])]
        release_decision = {
            "schema_version": 1,
            **decision.model_dump(mode="json"),
            "investigation": {
                "affected_query_ids": affected_query_ids,
                "query_route_template": f"#/runs/{quote(str(candidate_run_id), safe='')}/queries/{{query_id}}",
                "diff_route_template": (
                    f"#/runs/{quote(str(candidate_run_id), safe='')}/queries/{{query_id}}/diff?against="
                    f"{quote(str(baseline_run_id), safe='')}"
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

    engine = MetricsEngine()
    default_store = registry.get_store(registry.default_db_id)  # type: ignore[arg-type]

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

        return find_demo_context_for_registry(registry.db_paths)

    @app.post("/compare")
    async def compare_runs_endpoint(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if "selections" in body:
            parsed = MultiCompareRequest.model_validate(body)
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
            if len(parsed_legacy.run_ids) < 2:
                raise HTTPException(status_code=400, detail="Provide at least 2 run IDs")
            sole = registry.default_db_id
            selections = [(sole, run_id) for run_id in parsed_legacy.run_ids]
        else:
            raise HTTPException(status_code=400, detail="Provide selections or run_ids")
        for db_id, _ in selections:
            _store_for(db_id)
        result = await _build_comparison(selections, registry, engine)
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
            if manifest.get("forge_dataset_id"):
                run = {**run, "forge_dataset_id": manifest["forge_dataset_id"]}
            enriched.append(run)
        return enriched

    @db_router.post("/compare")
    async def compare_runs_in_db(db_id: str, req: CompareRequest) -> Dict[str, Any]:
        if len(req.run_ids) < 2:
            raise HTTPException(status_code=400, detail="Provide at least 2 run IDs")
        _store_for(db_id)
        selections = [(db_id, run_id) for run_id in req.run_ids]
        return await _build_comparison(selections, registry, engine)

    @db_router.get("/runs/{run_id}/metrics")
    async def get_run_metrics(db_id: str, run_id: str, include_branches: bool = False) -> Dict[str, Any]:
        store = _store_for(db_id)
        agg = await engine.aggregate(run_id, store)
        if not agg:
            traces = await store.list_traces(TraceQuery(run_id=run_id))
            if traces:
                qrels = await _resolve_qrels(store, run_id)
                await engine.compute_from_traces(run_id, store, traces, qrels)
                agg = await engine.aggregate(run_id, store)
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

    @db_router.get("/runs/{run_id}/query-labels")
    async def get_query_labels(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        diagnostics = await store.get_query_diagnostics(run_id)
        metrics_rows = await store.get_metrics(run_id)
        run_queries = await store.get_run_queries(run_id) if hasattr(store, "get_run_queries") else []

        text_by_id = {r["query_id"]: r["query_text"] for r in run_queries}
        actual_by_id: Dict[str, str] = {}
        for row in diagnostics:
            qid = row["query_id"]
            if qid not in actual_by_id:
                actual_by_id[qid] = row["difficulty_bucket"]

        predicted_by_id: Dict[str, Dict] = {}
        for row in metrics_rows:
            meta = row.get("query_metadata") or {}
            pred = meta.get("predicted_difficulty")
            if pred and row["query_id"] not in predicted_by_id:
                predicted_by_id[row["query_id"]] = {
                    "predicted_difficulty": pred,
                    "predicted_difficulty_proba": meta.get("predicted_difficulty_proba", {}),
                }

        from retrieval_observatory.classifier.labels import to_training_class
        from retrieval_observatory.metrics.diagnostics import predict_retrieval_risks

        items = []
        all_qids = sorted(set(actual_by_id) | set(predicted_by_id) | set(text_by_id))
        for qid in all_qids:
            actual_bucket = actual_by_id.get(qid, "unknown")
            actual_class = to_training_class(actual_bucket) or "unknown"
            pred_info = predicted_by_id.get(qid, {})
            predicted = pred_info.get("predicted_difficulty")
            agreement = _difficulty_agreement(actual_class, predicted)
            qtext = text_by_id.get(qid, "")
            items.append({
                "query_id": qid,
                "query_text": qtext,
                "actual_bucket": actual_bucket,
                "actual_class": actual_class,
                "predicted_difficulty": predicted,
                "predicted_difficulty_proba": pred_info.get("predicted_difficulty_proba"),
                "agreement": agreement,
                "predicted_risks": predict_retrieval_risks(qtext) if qtext else [],
            })
        return {"items": items}

    @db_router.get("/runs/{run_id}/classifier-calibration")
    async def get_classifier_calibration(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        metrics_rows = await store.get_metrics(run_id)
        diagnostics = await store.get_query_diagnostics(run_id)
        if not metrics_rows:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")

        predicted_by_id: Dict[str, str] = {}
        for row in metrics_rows:
            meta = row.get("query_metadata") or {}
            pred = meta.get("predicted_difficulty")
            if pred:
                predicted_by_id.setdefault(row["query_id"], pred)

        if not predicted_by_id:
            return {"run_id": run_id, "has_predictions": False, "classes": []}

        from retrieval_observatory.classifier.labels import to_training_class

        actual_by_id: Dict[str, str] = {}
        for row in diagnostics:
            qid = row["query_id"]
            if qid not in actual_by_id:
                mapped = to_training_class(row["difficulty_bucket"])
                if mapped:
                    actual_by_id[qid] = mapped

        # Final stage recall@10 per (query, pipeline), then mean across pipelines
        recall_rows = [
            r for r in metrics_rows
            if r["metric_name"] == "recall" and r["k"] == 10 and r["stage_index"] >= 0
        ]
        max_stage_by_pipeline: Dict[str, int] = {}
        for r in recall_rows:
            pid = r["pipeline_id"]
            max_stage_by_pipeline[pid] = max(max_stage_by_pipeline.get(pid, -1), r["stage_index"])

        per_query_recall: Dict[str, List[float]] = defaultdict(list)
        for r in recall_rows:
            pid = r["pipeline_id"]
            if r["stage_index"] != max_stage_by_pipeline.get(pid, r["stage_index"]):
                continue
            per_query_recall[r["query_id"]].append(r["value"])

        query_mean_recall = {qid: _mean(vals) for qid, vals in per_query_recall.items() if vals}

        classes = []
        actual_classes = []
        for cls in ("easy", "medium", "hard"):
            qids_pred = [qid for qid, pred in predicted_by_id.items() if pred == cls]
            scores_pred = [query_mean_recall[qid] for qid in qids_pred if qid in query_mean_recall]
            if not scores_pred:
                classes.append({
                    "class": cls,
                    "n": 0,
                    "mean_recall10": None,
                    "ci_low": None,
                    "ci_high": None,
                    "agreement_rate": None,
                })
            else:
                ci_low, ci_high = bootstrap_ci(scores_pred)
                agreements = [
                    1.0 for qid in qids_pred
                    if qid in actual_by_id and actual_by_id[qid] == cls
                ]
                agreement_rate = len(agreements) / len(qids_pred) if qids_pred else None
                classes.append({
                    "class": cls,
                    "n": len(scores_pred),
                    "mean_recall10": _mean(scores_pred),
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "agreement_rate": agreement_rate,
                })

            qids_actual = [qid for qid, actual in actual_by_id.items() if actual == cls]
            scores_actual = [query_mean_recall[qid] for qid in qids_actual if qid in query_mean_recall]
            if not scores_actual:
                actual_classes.append({
                    "class": cls,
                    "n": 0,
                    "mean_recall10": None,
                    "ci_low": None,
                    "ci_high": None,
                    "agreement_rate": None,
                })
            else:
                ci_low, ci_high = bootstrap_ci(scores_actual)
                actual_classes.append({
                    "class": cls,
                    "n": len(scores_actual),
                    "mean_recall10": _mean(scores_actual),
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "agreement_rate": None,
                })

        all_same_prediction = len(set(predicted_by_id.values())) <= 1 and len(predicted_by_id) > 0

        return {
            "run_id": run_id,
            "has_predictions": True,
            "classes": classes,
            "actual_classes": actual_classes,
            "all_same_prediction": all_same_prediction,
        }

    @db_router.get("/runs/{run_id}/overview")
    async def get_run_overview(db_id: str, run_id: str) -> Dict[str, Any]:
        from retrieval_observatory.sdk.report import build_run_report

        store = _store_for(db_id)
        runs = [run for run in await store.list_runs() if run["run_id"] == run_id]
        if not runs:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        metrics = await engine.aggregate(run_id, store)
        metrics_rows = await store.get_metrics(run_id)
        diagnostics = await store.get_query_diagnostics(run_id)
        manifest = await store.get_run_manifest(run_id)
        best = _headline_winner(metrics)
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
            "stage_contributions": _compute_stage_contributions(metrics, metrics_rows),
        }

    @db_router.get("/runs/{run_id}/report")
    async def get_run_report(db_id: str, run_id: str) -> Dict[str, Any]:
        """Canonical conclusion/evidence/provenance model for UI and agent clients."""
        overview = await get_run_overview(db_id, run_id)
        return overview["report"]

    @db_router.get("/runs/{run_id}/queries/{query_id}")
    async def get_query_result(db_id: str, run_id: str, query_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        traces = await store.list_traces(TraceQuery(run_id=run_id))
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
        db_id: str, run_id: str, query_id: str, against: str
    ) -> Dict[str, Any]:
        from dataclasses import asdict

        from retrieval_observatory.release.assessment import assess_evidence
        from retrieval_observatory.tracing.lineage import build_candidate_lineage
        from retrieval_observatory.tracing.lineage_diff import diff_candidate_lineage

        store = _store_for(db_id)
        candidate_traces = await store.list_traces(
            TraceQuery(run_id=run_id, query_id=query_id)
        )
        baseline_traces = await store.list_traces(
            TraceQuery(run_id=against, query_id=query_id)
        )
        if not candidate_traces or not baseline_traces:
            raise HTTPException(
                status_code=404,
                detail="Both selected runs must contain traces for the paired query.",
            )

        baseline_manifest = await store.get_run_manifest(against) or {}
        candidate_manifest = await store.get_run_manifest(run_id) or {}
        readiness = assess_evidence(
            None, baseline_manifest, candidate_manifest
        ).readiness["lineage_diff"]
        baseline_qrels = (await _resolve_qrels(store, against)).get(query_id, {})
        candidate_qrels = (await _resolve_qrels(store, run_id)).get(query_id, {})

        def mapping_complete(manifest: Dict[str, Any]) -> bool:
            return (
                ((manifest.get("evidence_profile") or {}).get("lineage") or {}).get(
                    "qrel_to_chunk_mapping_coverage"
                )
                == 1.0
            )

        baseline_by_pipeline = {trace.pipeline_id: trace for trace in baseline_traces}
        candidate_by_pipeline = {trace.pipeline_id: trace for trace in candidate_traces}
        common_pipelines = sorted(
            baseline_by_pipeline.keys() & candidate_by_pipeline.keys()
        )
        diffs = []
        for pipeline_id in common_pipelines:
            baseline_graph = build_candidate_lineage(
                baseline_by_pipeline[pipeline_id],
                qrels_for_query=baseline_qrels,
                qrel_chunk_mapping_complete=mapping_complete(baseline_manifest),
            )
            candidate_graph = build_candidate_lineage(
                candidate_by_pipeline[pipeline_id],
                qrels_for_query=candidate_qrels,
                qrel_chunk_mapping_complete=mapping_complete(candidate_manifest),
            )
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
        blocked_reasons = list(
            dict.fromkeys(
                reason
                for item in diffs
                if item["status"] == "BLOCK" and readiness.status != "BLOCK"
                for reason in item["reasons"]
            )
        )
        if not common_pipelines:
            blocked_reasons.append(
                "The selected runs have no aligned pipeline identity for this query."
            )
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
            "candidate_run_id": run_id,
            "query_id": query_id,
            "readiness": readiness_payload,
            "diffs": diffs,
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

    @db_router.get("/runs/{run_id}/queries/{query_id}/candidates/{candidate_id}")
    async def get_candidate_flow(
        db_id: str, run_id: str, query_id: str, candidate_id: str
    ) -> Dict[str, Any]:
        """Candidate passport with one-release document-flow compatibility aliases."""
        from retrieval_observatory.tracing.candidate_history import candidate_history
        from retrieval_observatory.tracing.replay import replay_assumptions

        store = _store_for(db_id)
        query_traces = await store.list_traces(TraceQuery(run_id=run_id, query_id=query_id))
        payload = await _query_lineage_payload(db_id, run_id, query_id)
        qrels = await _resolve_qrels(store, run_id)
        qrels_for_query = qrels.get(query_id, {})
        exact_matches = [
            node for node in payload["graph"]["nodes"] if node["candidate_id"] == candidate_id
        ]
        matches = exact_matches or [
            node
            for node in payload["graph"]["nodes"]
            if node.get("logical_chunk_id") == candidate_id
            or (node.get("source") or {}).get("document_id") == candidate_id
        ]
        if len(matches) > 1:
            payload["evidence_warnings"].append(
                {
                    "code": "candidate_present_in_multiple_traces",
                    "candidate_id": candidate_id,
                    "trace_ids": [node["trace_id"] for node in matches],
                }
            )
        if matches:
            primary = matches[0]
            history_doc_id = (primary.get("source") or {}).get("document_id") or candidate_id
            relevance = primary["relevance"]
            grade = relevance.get("grade")
            relevant = (
                True
                if relevance["kind"] == "relevant"
                else False
                if relevance["kind"] == "irrelevant"
                else None
            )
        else:
            history_doc_id = candidate_id
            grade = qrels_for_query.get(candidate_id)
            relevant = None if grade is None else int(grade) > 0
            primary = {
                "candidate_id": candidate_id,
                "logical_chunk_id": None,
                "source": {
                    "document_id": None,
                    "document_revision": None,
                    "content_hash": None,
                    "char_start": None,
                    "char_end": None,
                    "preview": None,
                },
                "parent_candidate_ids": [],
                "routes": [],
                "relevance": {
                    "kind": "unknown" if grade is None else "relevant" if relevant else "irrelevant",
                    "grade": int(grade) if grade is not None else None,
                    "evidence": "unavailable" if grade is None else "validated",
                },
                "outcome": {
                    "kind": "lineage_incomplete",
                    "evidence": "unavailable",
                    "operator_id": None,
                    "branch_id": None,
                    "reason": "candidate was not observed in query traces",
                },
                "lineage_evidence": "unavailable",
                "final_context_member": False,
                "removed_at": None,
                "removal_branch_id": None,
                "removal_reason": None,
                "removal_evidence": "unavailable",
                "derived_child_ids": [],
            }
            payload["readiness"] = {
                "scope": "lineage_diagnosis",
                "status": "BLOCK",
                "findings": [
                    {
                        "code": "candidate_not_observed",
                        "scope": "lineage_diagnosis",
                        "status": "BLOCK",
                        "observed": candidate_id,
                        "required": "candidate present in query-scoped traces",
                        "detail": "The requested candidate was not observed.",
                        "next_action": "Inspect an observed candidate ID or increase trace coverage.",
                    }
                ],
            }
        pipelines: List[Dict[str, Any]] = []
        for trace in query_traces:
            history = candidate_history(trace, history_doc_id)
            assumptions = None
            # If the doc was dropped, expose how a counterfactual replay of the dropping
            # operator would be constructed, so the drop explanation is inspectable.
            if history.dropped_at:
                try:
                    assumptions = replay_assumptions(trace, history.dropped_at).__dict__
                except ValueError:
                    assumptions = None
            pipelines.append(
                {
                    "pipeline_id": trace.pipeline_id,
                    "trace_id": trace.trace_id,
                    "history": history.to_dict(),
                    "drop_replay_assumptions": assumptions,
                }
            )
        return {
            **primary,
            "run_id": run_id,
            "query_id": query_id,
            "doc_id": history_doc_id,
            "relevant": relevant,
            "grade": int(grade) if grade is not None else None,
            "readiness": payload["readiness"],
            "evidence_warnings": payload["evidence_warnings"],
            "trace_passports": matches,
            "pipelines": pipelines,
        }

    @db_router.get("/runs/{run_id}/stage-matrix")
    async def get_stage_matrix(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        agg = await engine.aggregate(run_id, store)
        run_rows = [run for run in await store.list_runs() if run["run_id"] == run_id]
        config = json.loads(run_rows[0]["config_json"]) if run_rows else {}
        costs = config.get("costs", {})
        cells = []
        for key, value in agg.items():
            if value["stage_index"] < 0:
                continue
            cells.append({"metric": key, "estimated_cost_per_1k": _pipeline_cost_per_1k(config, value["pipeline_id"], costs), **value})
        return {"run_id": run_id, "cells": cells}

    @db_router.get("/runs/{run_id}/pareto-frontier")
    async def get_pareto_frontier(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        agg = await engine.aggregate(run_id, store)
        if not agg:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")

        run_rows = [run for run in await store.list_runs() if run["run_id"] == run_id]
        config = json.loads(run_rows[0]["config_json"]) if run_rows else {}
        costs = config.get("costs", {})
        manifest = await store.get_run_manifest(run_id)

        final_metrics = _extract_final_stage_metrics(agg)
        all_pipeline_ids = _pareto_pipeline_ids_in_agg(agg)
        omitted = sorted(all_pipeline_ids - set(final_metrics.keys()))
        pareto_inputs: List[ParetoPipelineInput] = []
        for pipeline_id, metrics in final_metrics.items():
            cost = _pipeline_cost_per_1k(config, pipeline_id, costs)
            pareto_inputs.append(
                ParetoPipelineInput(
                    pipeline_id=pipeline_id,
                    stage_index=metrics["stage_index"],
                    ndcg10=metrics["ndcg10"],
                    recall10=metrics["recall10"],
                    latency_p50=metrics["latency_p50"],
                    latency_p95=metrics["latency_p95"],
                    cost_per_1k=cost if cost > 0 else None,
                    ndcg10_ci_low=metrics.get("ndcg10_ci_low"),
                    ndcg10_ci_high=metrics.get("ndcg10_ci_high"),
                    recall10_ci_low=metrics.get("recall10_ci_low"),
                    recall10_ci_high=metrics.get("recall10_ci_high"),
                )
            )

        result = compute_pareto_frontier(pareto_inputs)
        latency_budget_ms = manifest.get("latency_budget_ms") if manifest else None

        return {
            "run_id": run_id,
            "objectives": result.objectives,
            "cost_included": result.cost_included,
            "cost_excluded_reason": result.cost_excluded_reason,
            "latency_budget_ms": latency_budget_ms,
            "omitted_pipelines": omitted,
            "omitted_reason": (
                "Missing one or more of NDCG@10, Recall@10, or end-to-end latency (P50/P95)."
                if omitted
                else None
            ),
            "pipelines": [
                {
                    "pipeline_id": row.pipeline_id,
                    "stage_index": row.stage_index,
                    "label": row.pipeline_id,
                    "metrics": {**row.metrics, **_pareto_quality_ci(agg, row.pipeline_id, row.stage_index)},
                    "is_pareto_optimal": row.is_pareto_optimal,
                    "dominated_by": row.dominated_by,
                }
                for row in result.pipelines
            ],
            "frontier_order": result.frontier_order,
        }

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
    ) -> Dict[str, Any]:
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

    @db_router.get("/runs/{run_id}/operator-attribution")
    async def get_operator_attribution(
        db_id: str,
        run_id: str,
        metric: str = "recall",
        k: int = 10,
    ) -> List[Dict[str, Any]]:
        store = _store_for(db_id)
        traces = await store.list_traces(TraceQuery(run_id=run_id))
        qrels = await _resolve_qrels(store, run_id)
        op_ids = sorted({span.op_id for trace in traces for span in trace.spans})
        out: List[Dict[str, Any]] = []
        for op_id in op_ids:
            for result in operator_marginal_contribution(traces, op_id=op_id, qrels=qrels, metric=metric, k=k):
                out.append(result.__dict__)
        return out

    @db_router.get("/runs/{run_id}/pipeline-graph")
    async def get_pipeline_graph(db_id: str, run_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Canonical PipelineGraph projection (nodes + edges, every metric with its CI or null)
        built from persisted traces + aggregated metrics. Drives the dashboard DAG view, the
        offline HTML diagram, and the MCP get_pipeline_diagram tool from one contract."""
        from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs

        store = _store_for(db_id)
        agg = await engine.aggregate(run_id, store)
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

    @db_router.get("/runs/{run_id}/traces/{trace_id}/operator/{op_id}/diff")
    async def get_operator_diff(
        db_id: str, run_id: str, trace_id: str, op_id: str,
    ) -> Dict[str, Any]:
        """Per-query operator-level candidate diff for OperatorInspector."""
        from retrieval_observatory.tracing.replay import simulate_without_operator

        store = _store_for(db_id)
        trace = await store.get_trace(trace_id)
        if trace is None or trace.run_id != run_id:
            raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
        span = next((s for s in trace.spans if s.op_id == op_id), None)
        if span is None:
            raise HTTPException(status_code=404, detail=f"Operator '{op_id}' not found")
        replay = simulate_without_operator(trace, op_id)
        from retrieval_observatory.tracing.attribution import _find_final_span
        cf_final = _find_final_span(replay.trace) if replay.trace else None
        return {
            "op_id": op_id,
            "op_type": span.op_type,
            "replay_policy": span.replay_policy,
            "result_status": replay.status,
            "evidence_class": replay.evidence_class,
            "reason": replay.reason,
            "unsupported_descendants": replay.unsupported_descendants,
            "assumptions": replay.assumptions.__dict__,
            "inputs": [{"doc_id": c.doc_id, "score": c.score, "rank": c.rank} for c in span.inputs],
            "outputs": [{"doc_id": c.doc_id, "score": c.score, "rank": c.rank} for c in span.outputs],
            "without_operator": [
                {"doc_id": c.doc_id, "score": c.score, "rank": c.rank}
                for c in (cf_final.outputs if cf_final else [])
            ],
        }

    @db_router.get("/runs/{run_id}/traces/{trace_id}/miss-attribution")
    async def get_miss_attribution(
        db_id: str, run_id: str, trace_id: str, k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Miss attribution for a single query trace."""
        from retrieval_observatory.tracing.replay import attribute_miss as _attr_miss

        store = _store_for(db_id)
        trace = await store.get_trace(trace_id)
        if trace is None or trace.run_id != run_id:
            raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
        qrels = await _resolve_qrels(store, run_id)
        misses = await _attr_miss(trace, qrels=qrels, k=k)
        return [
            {
                "query_id": m.query_id,
                "doc_id": m.doc_id,
                "miss_type": m.miss_type,
                "op_id": m.op_id,
                "confidence": m.confidence,
                "note": m.note,
            }
            for m in misses
        ]

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

    # ---------------------------------------------------------------------------
    # Test Sets endpoints — synthetic dataset management
    # ---------------------------------------------------------------------------
    forge_router = APIRouter(prefix="/forge")

    @app.get("/dbs/{db_id}/forge/datasets")
    @forge_router.get("/datasets")
    async def list_forge_datasets(db_id: str = "") -> List[Dict[str, Any]]:
        """List all Test Sets-generated synthetic datasets saved in the store."""
        try:
            store = _evidence_store(db_id)
            if store and hasattr(store, "get_forge_datasets"):
                return await store.get_forge_datasets()
        except HTTPException:
            raise
        except Exception:
            pass
        return []

    @app.get("/dbs/{db_id}/forge/datasets/{dataset_id}")
    @forge_router.get("/datasets/{dataset_id}")
    async def get_forge_dataset(dataset_id: str, db_id: str = "") -> Dict[str, Any]:
        """Return summary and scenario breakdown for a Test Sets dataset."""
        try:
            store = _evidence_store(db_id)
            if store:
                datasets = await store.get_forge_datasets()
                dataset = next((d for d in datasets if d["dataset_id"] == dataset_id), None)
                if dataset:
                    scenarios = await store.get_forge_scenarios(dataset_id) if hasattr(store, "get_forge_scenarios") else []
                    summary = dataset.get("summary") or {}
                    coverage = float(summary.get("validation_coverage", 0.0))
                    return {
                        **dataset,
                        "scenarios": scenarios,
                        "validation_coverage": round(coverage, 4),
                    }
        except HTTPException:
            raise
        except Exception:
            pass
        raise HTTPException(status_code=404, detail=f"Test Sets dataset {dataset_id!r} not found")

    @app.get("/dbs/{db_id}/forge/datasets/{dataset_id}/queries")
    @forge_router.get("/datasets/{dataset_id}/queries")
    async def get_forge_dataset_queries(
        dataset_id: str,
        scenario_type: str = "",
        difficulty: str = "",
        query_type: str = "",
        validated_only: bool = False,
        limit: int = 200,
        offset: int = 0,
        db_id: str = "",
    ) -> Dict[str, Any]:
        """Return a stable, paginated Test Set query and provenance envelope."""
        try:
            store = _evidence_store(db_id)
            if store and hasattr(store, "get_forge_queries"):
                items = await store.get_forge_queries(
                    dataset_id,
                    scenario_type=scenario_type or None,
                    difficulty=difficulty or None,
                    query_type=query_type or None,
                    validated_only=validated_only,
                    limit=limit,
                    offset=offset,
                )
                all_items = await store.get_forge_queries(
                    dataset_id,
                    scenario_type=scenario_type or None,
                    difficulty=difficulty or None,
                    query_type=query_type or None,
                    validated_only=validated_only,
                    limit=100000,
                    offset=0,
                )
                datasets = await store.get_forge_datasets()
                dataset = next((item for item in datasets if item["dataset_id"] == dataset_id), {})
                return {
                    "test_set_id": dataset_id,
                    "provenance": dataset.get("provenance") or dataset.get("metadata") or {},
                    "items": items,
                    "total": len(all_items),
                    "limit": limit,
                    "offset": offset,
                    "next_offset": offset + len(items) if offset + len(items) < len(all_items) else None,
                }
        except HTTPException:
            raise
        except Exception:
            pass
        return {"test_set_id": dataset_id, "provenance": {}, "items": [], "total": 0, "limit": limit, "offset": offset, "next_offset": None}

    @app.get("/dbs/{db_id}/forge/datasets/{dataset_id}/runs")
    @forge_router.get("/datasets/{dataset_id}/runs")
    async def get_forge_dataset_runs(dataset_id: str, db_id: str = "") -> List[Dict[str, Any]]:
        """Return benchmark runs executed against this Test Sets dataset.

        Prefer manifest ``forge_dataset_id``; fall back to output_dir text match for older runs.
        """
        try:
            store = _evidence_store(db_id)
            if not store:
                return []
            datasets = await store.get_forge_datasets()
            dataset = next((d for d in datasets if d["dataset_id"] == dataset_id), None)
            output_dir = (dataset.get("output_dir") or "").rstrip("/") if dataset else ""
            runs = await store.list_runs()
            matched = []
            seen: set[str] = set()
            for r in runs:
                run_id = r.get("run_id")
                if not run_id or run_id in seen:
                    continue
                manifest = await store.get_run_manifest(run_id) if hasattr(store, "get_run_manifest") else None
                if manifest and manifest.get("forge_dataset_id") == dataset_id:
                    matched.append({
                        "run_id": run_id,
                        "experiment_name": r.get("experiment_name"),
                        "started_at": r.get("started_at"),
                        "forge_dataset_id": dataset_id,
                    })
                    seen.add(run_id)
                    continue
                cfg = r.get("config_json") or ""
                if output_dir and output_dir in cfg:
                    matched.append({
                        "run_id": run_id,
                        "experiment_name": r.get("experiment_name"),
                        "started_at": r.get("started_at"),
                    })
                    seen.add(run_id)
            return matched
        except HTTPException:
            raise
        except Exception:
            pass
        return []

    @app.get("/dbs/{db_id}/forge/datasets/{dataset_id}/scenarios")
    @forge_router.get("/datasets/{dataset_id}/scenarios")
    async def get_forge_dataset_scenarios(dataset_id: str, db_id: str = "") -> List[Dict[str, Any]]:
        """Return scenarios for a Test Sets dataset."""
        try:
            store = _evidence_store(db_id)
            if store and hasattr(store, "get_forge_scenarios"):
                return await store.get_forge_scenarios(dataset_id)
        except HTTPException:
            raise
        except Exception:
            pass
        return []

    app.include_router(forge_router)

    @app.get("/dbs/{db_id}/query/{query_id}/lineage")
    @app.get("/query/{query_id}/lineage")
    async def get_query_lineage(query_id: str, db_id: str = "") -> Dict[str, Any]:
        store = _evidence_store(db_id)
        if not store or not hasattr(store, "get_query_lineage"):
            raise HTTPException(status_code=404, detail="Lineage not available")
        return await store.get_query_lineage(query_id)

    advisor_router = APIRouter(prefix="/advisor")

    @app.get("/dbs/{db_id}/advisor/recommendations")
    @advisor_router.get("/recommendations")
    async def advisor_recommendations(run_id: str, db_id: str = "") -> Dict[str, Any]:
        from retrieval_observatory.advisor.recommend import recommend

        from dataclasses import asdict

        store = _evidence_store(db_id)
        recs = await recommend(run_id, store)
        return {
            "run_id": run_id,
            "recommendations": [asdict(r) for r in recs],
        }

    @app.get("/dbs/{db_id}/advisor/regressions")
    @advisor_router.get("/regressions")
    async def advisor_regressions(baseline: str, candidate: str, db_id: str = "") -> Dict[str, Any]:
        from retrieval_observatory.advisor.regression import detect_regressions

        store = _evidence_store(db_id)
        validity = comparison_validity([
            await store.get_run_manifest(baseline),
            await store.get_run_manifest(candidate),
        ])
        findings = await detect_regressions(baseline, candidate, store, engine=engine)
        return {
            "baseline": baseline,
            "candidate": candidate,
            "validity": validity.to_dict(),
            "regressions": [
                {
                    "metric": f.metric,
                    "before": f.before,
                    "after": f.after,
                    "delta": f.delta,
                    "q_value": f.q_value,
                    "severity": f.severity,
                    "n_pairs": f.n_pairs,
                    "p_value": f.p_value,
                    "effect_threshold": f.effect_threshold,
                    "decision": f.decision,
                }
                for f in findings
            ],
        }

    @app.get("/dbs/{db_id}/advisor/reliability")
    @advisor_router.get("/reliability")
    async def advisor_reliability(run_id: str, db_id: str = "") -> Dict[str, Any]:
        from retrieval_observatory.advisor.recommend import compute_reliability

        store = _evidence_store(db_id)
        score = await compute_reliability(run_id, store, engine=engine)
        return {"run_id": run_id, **score.as_dict()}

    @app.get("/dbs/{db_id}/advisor/reliability/history")
    @advisor_router.get("/reliability/history")
    async def advisor_reliability_history(
        run_id: str | None = None,
        limit: int = 50,
        db_id: str = "",
    ) -> Dict[str, Any]:
        from retrieval_observatory.advisor.trends import get_reliability_trends

        store = _evidence_store(db_id)
        history = await get_reliability_trends(store, run_id=run_id, limit=limit)
        return {"history": history}

    app.include_router(advisor_router)

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
            return [_dataclass_asdict(summary) for summary in await store.list_services()]
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
        from datetime import datetime
        store = _production_store(db_id)
        if store and hasattr(store, "list_traces"):
            base = TraceQuery(
                service_id=service_id,
                since=datetime.fromisoformat(since) if since else None,
                until=datetime.fromisoformat(until) if until else None,
                status=status or None, limit=limit, offset=offset)
            traces = await store.list_traces(base)
            all_matches = await store.list_traces(TraceQuery(service_id=service_id, since=base.since, until=base.until, status=base.status, limit=100000))
            total = len(all_matches)
            return {"items": [trace.to_dict() for trace in traces], "total": total, "limit": limit, "offset": offset, "next_offset": offset + len(traces) if offset + len(traces) < total else None}
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "next_offset": None}

    @app.get("/dbs/{db_id}/production/topology-variants")
    @production_router.get("/topology-variants")
    async def topology_variants(service_id: str, limit: int = 50, offset: int = 0, db_id: str = "") -> Dict[str, Any]:
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
                return t.to_dict()
        raise HTTPException(status_code=404, detail=f"Trace {trace_id!r} not found")

    @app.get("/dbs/{db_id}/production/summary")
    @production_router.get("/summary")
    async def trace_summary(service_id: str, since: str = "", until: str = "", db_id: str = "") -> Dict[str, Any]:
        from datetime import datetime
        store = _production_store(db_id)
        if not (store and hasattr(store, "list_traces")):
            return {}
        traces = await store.list_traces(TraceQuery(service_id=service_id, since=datetime.fromisoformat(since) if since else None, until=datetime.fromisoformat(until) if until else None, limit=100000))
        rows = [_monitor_trace(trace) for trace in traces]
        from retrieval_observatory.tracing.monitor.distribution import summarize
        return summarize(rows)

    @app.get("/dbs/{db_id}/production/distribution")
    @production_router.get("/distribution")
    async def trace_distribution(service_id: str, since: str = "", until: str = "", db_id: str = "") -> Dict[str, Any]:
        from datetime import datetime
        store = _production_store(db_id)
        if not (store and hasattr(store, "list_traces")):
            return {}
        rows = [_monitor_trace(trace) for trace in await store.list_traces(TraceQuery(service_id=service_id, since=datetime.fromisoformat(since) if since else None, until=datetime.fromisoformat(until) if until else None, limit=100000))]
        from retrieval_observatory.tracing.monitor.distribution import compute_distribution
        return compute_distribution(rows)

    @app.get("/dbs/{db_id}/production/drift")
    @production_router.get("/drift")
    async def trace_drift(service_id: str, baseline: str = "", recent: str = "", db_id: str = "") -> List[Dict[str, Any]]:
        """Compare a baseline window vs a recent window. Defaults: prior 7d vs last 24h."""
        from datetime import datetime, timedelta, timezone
        store = _production_store(db_id)
        if not (store and hasattr(store, "list_traces")):
            return []
        now = datetime.now(timezone.utc)
        recent_since = recent or (now - timedelta(hours=24)).isoformat()
        baseline_until = recent_since
        baseline_since = baseline or (now - timedelta(days=8)).isoformat()
        recent_rows = [_monitor_trace(trace) for trace in await store.list_traces(TraceQuery(service_id=service_id, since=datetime.fromisoformat(recent_since), limit=10000))]
        baseline_rows = [_monitor_trace(trace) for trace in await store.list_traces(TraceQuery(service_id=service_id, since=datetime.fromisoformat(baseline_since), until=datetime.fromisoformat(baseline_until), limit=10000))]
        from retrieval_observatory.tracing.monitor.drift import compute_drift
        findings = compute_drift(baseline_rows, recent_rows)
        for finding in findings:
            finding["baseline_window"] = {"since": baseline_since, "until": baseline_until}
            finding["recent_window"] = {"since": recent_since, "until": None}
            finding["sample_limited"] = len(baseline_rows) == 10000 or len(recent_rows) == 10000
        return findings

    @app.get("/dbs/{db_id}/production/hotspots")
    @production_router.get("/hotspots")
    async def trace_hotspots(service_id: str, since: str = "", until: str = "", db_id: str = "") -> List[Dict[str, Any]]:
        from datetime import datetime
        store = _production_store(db_id)
        if not (store and hasattr(store, "list_traces")):
            return []
        rows = [_monitor_trace(trace) for trace in await store.list_traces(TraceQuery(service_id=service_id, since=datetime.fromisoformat(since) if since else None, until=datetime.fromisoformat(until) if until else None, limit=10000))]
        from retrieval_observatory.tracing.monitor.hotspots import compute_hotspots
        return compute_hotspots(rows)

    @app.get("/dbs/{db_id}/production/clusters")
    @production_router.get("/clusters")
    async def trace_clusters(service_id: str, since: str = "", until: str = "", db_id: str = "") -> List[Dict[str, Any]]:
        from datetime import datetime
        store = _production_store(db_id)
        if not (store and hasattr(store, "list_traces")):
            return []
        rows = [_monitor_trace(trace) for trace in await store.list_traces(TraceQuery(service_id=service_id, since=datetime.fromisoformat(since) if since else None, until=datetime.fromisoformat(until) if until else None, limit=100000))]
        from retrieval_observatory.tracing.monitor.cluster import compute_clusters
        return compute_clusters(rows)

    app.include_router(production_router)

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

        @app.get("/runs/{run_id}/query-labels")
        async def legacy_query_labels(run_id: str) -> Dict[str, Any]:
            return await get_query_labels(_sole_db, run_id)

        @app.get("/runs/{run_id}/classifier-calibration")
        async def legacy_classifier_calibration(run_id: str) -> Dict[str, Any]:
            return await get_classifier_calibration(_sole_db, run_id)

        @app.get("/runs/{run_id}/overview")
        async def legacy_overview(run_id: str) -> Dict[str, Any]:
            return await get_run_overview(_sole_db, run_id)

        @app.get("/runs/{run_id}/queries/{query_id}")
        async def legacy_query_result(run_id: str, query_id: str) -> Dict[str, Any]:
            return await get_query_result(_sole_db, run_id, query_id)

        @app.get("/runs/{run_id}/stage-matrix")
        async def legacy_stage_matrix(run_id: str) -> Dict[str, Any]:
            return await get_stage_matrix(_sole_db, run_id)

        @app.get("/runs/{run_id}/pareto-frontier")
        async def legacy_pareto(run_id: str) -> Dict[str, Any]:
            return await get_pareto_frontier(_sole_db, run_id)

        @app.post("/runs/{run_id}/traces")
        async def legacy_ingest_trace(run_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
            return await ingest_trace(_sole_db, run_id, payload)

        @app.get("/runs/{run_id}/traces")
        async def legacy_list_traces(run_id: str) -> List[Dict[str, Any]]:
            return await list_run_traces(_sole_db, run_id)

        @app.get("/runs/{run_id}/traces/{trace_id}")
        async def legacy_get_trace(run_id: str, trace_id: str) -> Dict[str, Any]:
            return await get_run_trace(_sole_db, run_id, trace_id)

        @app.get("/runs/{run_id}/operator-attribution")
        async def legacy_operator_attribution(run_id: str, metric: str = "recall", k: int = 10) -> List[Dict[str, Any]]:
            return await get_operator_attribution(_sole_db, run_id, metric, k)

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
            [(db_id, baseline_run_id), (db_id, candidate_run_id)], registry, engine
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
        agg = await engine.aggregate(run_id, store)
        if not agg:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")
        traces = await store.list_traces(TraceQuery(run_id=run_id))
        if not traces:
            raise HTTPException(
                status_code=404,
                detail=f"Run '{run_id}' has no execution traces yet -- no diagram to render.",
            )
        graphs = build_pipeline_graphs(agg, traces)
        operator_dag = await get_operator_dag(db_id, run_id)
        return {
            "run_id": run_id,
            "pipelines": [g.to_dict() for g in graphs],
            "operator_dag": operator_dag,
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


def _difficulty_agreement(actual_class: str, predicted: str | None) -> str | None:
    """Return match, adjacent, or mismatch for 3-class labels."""
    if not predicted or actual_class == "unknown":
        return None
    if actual_class == predicted:
        return "match"
    order = {"easy": 0, "medium": 1, "hard": 2}
    if abs(order.get(actual_class, 1) - order.get(predicted, 1)) == 1:
        return "adjacent"
    return "mismatch"


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


def _compute_stage_contributions(metrics: Dict[str, Any], metrics_rows: List[Dict]) -> List[Dict]:
    """Return cross-pipeline, within-pipeline, and fused-arm ablation deltas."""
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

            b_scores = {
                r["query_id"]: r["value"]
                for r in metrics_rows
                if r["pipeline_id"] == before_id
                and r["stage_index"] == before_stage
                and r.get("branch_id") == before_branch
                and r["metric_name"] == mname
                and r["k"] == k
            }
            a_scores = {
                r["query_id"]: r["value"]
                for r in metrics_rows
                if r["pipeline_id"] == after_id
                and r["stage_index"] == after_stage
                and r.get("branch_id") == after_branch
                and r["metric_name"] == mname
                and r["k"] == k
            }
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
                r["value"]
                for r in metrics_rows
                if r["pipeline_id"] == metric_pipeline_id
                and r["stage_index"] == metric_stage
                and r.get("branch_id") == branch
                and r["metric_name"] == "latency_ms"
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
        for before_stage, after_stage in zip(ordered, ordered[1:]):
            deltas, lat_before, lat_after, has_indeterminate = _build_delta(pid, before_stage, None, pid, after_stage, None)
            contributions.append(
                {
                    "comparison_tier": "within_pipeline_stage",
                    "from_pipeline": f"{pid}:stage{before_stage}",
                    "to_pipeline": f"{pid}:stage{after_stage}",
                    "pipeline_id": pid,
                    "deltas": deltas,
                    "latency_p50_before_ms": lat_before,
                    "latency_p50_after_ms": lat_after,
                    "latency_delta_ms": (lat_after - lat_before) if lat_before is not None and lat_after is not None else None,
                    "indeterminate": has_indeterminate,
                }
            )

    for pid, stages in keys_by_pipeline_branch.items():
        for stage_index, branches in stages.items():
            for branch_id in sorted(branches):
                deltas, lat_before, lat_after, has_indeterminate = _build_delta(pid, stage_index, branch_id, pid, stage_index, None)
                contributions.append(
                    {
                        "comparison_tier": "within_stage_arm",
                        "from_pipeline": f"{pid}:stage{stage_index}:{branch_id}",
                        "to_pipeline": f"{pid}:stage{stage_index}:fused",
                        "pipeline_id": pid,
                        "stage_index": stage_index,
                        "branch_id": branch_id,
                        "deltas": deltas,
                        "latency_p50_before_ms": lat_before,
                        "latency_p50_after_ms": lat_after,
                        "latency_delta_ms": (lat_after - lat_before) if lat_before is not None and lat_after is not None else None,
                        "indeterminate": has_indeterminate,
                    }
                )

    return contributions


def _pipeline_cost_per_1k(config: Dict[str, Any], pipeline_id: str, costs: Dict[str, Dict[str, float]]) -> float:
    from retrieval_observatory.config.cost import pipeline_cost_per_1k

    return pipeline_cost_per_1k(config, pipeline_id, costs)


def _lookup_agg_metric(
    agg: Dict[str, Any],
    pipeline_id: str,
    stage_index: int,
    metric_name: str,
    k: int = 0,
) -> Dict[str, Any] | None:
    for value in agg.values():
        if value.get("pipeline_id") != pipeline_id:
            continue
        if value.get("stage_index") != stage_index:
            continue
        if value.get("metric_name") != metric_name:
            continue
        if value.get("k", 0) != k:
            continue
        return value
    return None


def _extract_final_stage_metrics(agg: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Return per-pipeline metrics needed for Pareto analysis: final-stage QUALITY, but
    end-to-end LATENCY.

    Quality (NDCG/Recall) is read from the pipeline's final stage. Latency is read from the
    end-to-end distribution stored at stage_index=-1 (the joint per-query latency) for
    multi-stage pipelines, so a hybrid+rerank pipeline is plotted at its true total latency,
    not the reranker's stage-local latency. Single-stage pipelines have no stage -1 entry, so
    their final-stage latency is already end-to-end and is used directly."""
    by_pipeline: Dict[str, Dict[int, Dict[tuple, Dict[str, Optional[float]]]]] = defaultdict(lambda: defaultdict(dict))
    e2e_latency: Dict[str, Dict[tuple, float]] = defaultdict(dict)
    for value in agg.values():
        if value.get("branch_id"):
            continue
        stage_index = value.get("stage_index", -1)
        metric_key = (value["metric_name"], value.get("k", 0))
        if stage_index < 0:
            # End-to-end latency percentiles live at stage -1 for multi-stage pipelines.
            if value["metric_name"] in ("latency_p50", "latency_p95"):
                e2e_latency[value["pipeline_id"]][metric_key] = value["mean"]
            continue
        by_pipeline[value["pipeline_id"]][stage_index][metric_key] = {
            "mean": value["mean"],
            "ci_low": value.get("ci_low"),
            "ci_high": value.get("ci_high"),
        }

    quality_required = {("ndcg", 10): "ndcg10", ("recall", 10): "recall10"}
    latency_required = {("latency_p50", 0): "latency_p50", ("latency_p95", 0): "latency_p95"}

    final_metrics: Dict[str, Dict[str, float | int]] = {}
    for pipeline_id, stages in by_pipeline.items():
        final_stage = max(stages.keys())
        stage_metrics = stages[final_stage]
        row: Dict[str, float | int] = {"stage_index": final_stage}
        complete = True
        for metric_key, field in quality_required.items():
            if metric_key not in stage_metrics:
                complete = False
                break
            entry = stage_metrics[metric_key]
            row[field] = entry["mean"]
            row[f"{field}_ci_low"] = entry.get("ci_low")
            row[f"{field}_ci_high"] = entry.get("ci_high")
        if not complete:
            continue
        for metric_key, field in latency_required.items():
            # Prefer end-to-end latency (stage -1); fall back to final-stage latency for
            # single-stage pipelines that have no joint-distribution entry.
            if metric_key in e2e_latency.get(pipeline_id, {}):
                row[field] = e2e_latency[pipeline_id][metric_key]
            elif metric_key in stage_metrics:
                row[field] = stage_metrics[metric_key]["mean"]
            else:
                complete = False
                break
        if complete:
            final_metrics[pipeline_id] = row
    return final_metrics


def _pareto_quality_ci(
    agg: Dict[str, Any], pipeline_id: str, stage_index: int
) -> Dict[str, float | None]:
    """Bootstrap CI bounds for quality metrics on the pipeline's final stage."""
    out: Dict[str, float | None] = {}
    for metric_name, k, prefix in (("ndcg", 10, "ndcg@10"), ("recall", 10, "recall@10")):
        entry = _lookup_agg_metric(agg, pipeline_id, stage_index, metric_name, k)
        if entry is None:
            continue
        out[f"{prefix}_ci_low"] = entry.get("ci_low")
        out[f"{prefix}_ci_high"] = entry.get("ci_high")
    return out


def _pareto_pipeline_ids_in_agg(agg: Dict[str, Any]) -> set[str]:
    return {
        value["pipeline_id"]
        for value in agg.values()
        if value.get("stage_index", -1) >= 0 and not value.get("branch_id")
    }
