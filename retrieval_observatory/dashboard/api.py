from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import numpy as np

from retrieval_observatory.metrics.pareto import ParetoPipelineInput, compute_pareto_frontier
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.comparison import paired_scores_by_query, pipeline_pairs, parse_metric_key
from retrieval_observatory.metrics.diagnostics import aggregate_diagnostics
from retrieval_observatory.metrics.significance import benjamini_hochberg, bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore

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

try:
    from pydantic import BaseModel as _BaseModel

    class CompareRequest(_BaseModel):
        run_ids: List[str]

    class RunSelection(_BaseModel):
        db_id: str
        run_id: str

    class MultiCompareRequest(_BaseModel):
        selections: List[RunSelection]
except ImportError:
    CompareRequest = None  # type: ignore
    RunSelection = None  # type: ignore
    MultiCompareRequest = None  # type: ignore


def _selection_key(db_id: str, run_id: str) -> str:
    return f"{db_id}/{run_id}"


def _dataset_fingerprint(manifest: Dict[str, Any] | None) -> str | None:
    if not manifest:
        return None
    dataset = manifest.get("dataset")
    if not dataset:
        return None
    return json.dumps(dataset, sort_keys=True, default=str)


def _compare_warnings(fingerprints: List[str | None]) -> List[str]:
    known = {fp for fp in fingerprints if fp is not None}
    if len(known) > 1:
        return ["Runs use different datasets; metrics may not be comparable."]
    return []


async def _build_comparison(
    selections: List[tuple],
    registry: DbRegistry,
    engine: MetricsEngine,
) -> Dict[str, Any]:
    """Compare runs across one or more databases. selections: [(db_id, run_id), ...]."""
    if len(selections) < 2:
        raise ValueError("Provide at least 2 runs")

    warnings: List[str] = []
    fingerprints: List[str | None] = []
    for db_id, run_id in selections:
        store = registry.get_store(db_id)
        manifest = await store.get_run_manifest(run_id)
        fingerprints.append(_dataset_fingerprint(manifest))
    warnings.extend(_compare_warnings(fingerprints))

    keys = [_selection_key(db_id, run_id) for db_id, run_id in selections]
    aggregated: Dict[str, Dict] = {}
    for (db_id, run_id), key in zip(selections, keys):
        store = registry.get_store(db_id)
        aggregated[key] = await engine.aggregate(run_id, store)

    all_metric_keys = sorted(set().union(*(agg.keys() for agg in aggregated.values())))
    comparison = []
    same_dataset = len({fp for fp in fingerprints if fp is not None}) <= 1

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
        if same_dataset and len(selections) >= 2:
            db_a, run_a = selections[0]
            db_b, run_b = selections[1]
            store_a = registry.get_store(db_a)
            store_b = registry.get_store(db_b)
            metrics_1 = await store_a.get_metrics(run_a)
            metrics_2 = await store_b.get_metrics(run_b)
            s1, s2, n_pairs = paired_scores_by_query(metrics_1, metrics_2, metric_key)
            if s1 and s2:
                try:
                    entry["p_value"] = paired_bootstrap_test(s1, s2)
                    entry["paired_n"] = n_pairs
                except Exception:
                    pass
        comparison.append(entry)

    return {
        "comparison": comparison,
        "selections": [{"db_id": db_id, "run_id": run_id} for db_id, run_id in selections],
        "run_ids": [run_id for _, run_id in selections],
        "warnings": warnings,
    }


def create_app(
    registry: DbRegistry | None = None,
    db_path: str | None = None,
    db_paths: List[str] | None = None,
    enable_uploads: bool = True,
):
    try:
        from fastapi import APIRouter, Body, FastAPI, File, HTTPException, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError as e:
        raise ImportError("Dashboard requires fastapi. Install with: pip install fastapi") from e

    if registry is None:
        paths = db_paths if db_paths else ([db_path] if db_path else [".retobs/results.db"])
        registry = DbRegistry(paths)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await registry.init_all()
        yield

    app = FastAPI(title="Retrieval Observatory", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    engine = MetricsEngine()
    default_store = registry.get_store(registry.default_db_id)  # type: ignore[arg-type]

    def _store_for(db_id: str) -> SQLiteStore:
        try:
            return registry.get_store(db_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown database '{db_id}'")

    @app.get("/dbs")
    async def list_databases() -> List[Dict]:
        return await registry.list_sources()

    @app.post("/compare")
    async def compare_runs_endpoint(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if "selections" in body:
            parsed = MultiCompareRequest.model_validate(body)
            if len(parsed.selections) < 2:
                raise HTTPException(status_code=400, detail="Provide at least 2 run selections")
            selections = [(s.db_id, s.run_id) for s in parsed.selections]
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

    db_router = APIRouter(prefix="/dbs/{db_id}")

    @db_router.get("/runs")
    async def list_runs(db_id: str) -> List[Dict]:
        _store_for(db_id)
        return await registry.list_runs(db_id)

    @db_router.post("/compare")
    async def compare_runs_in_db(db_id: str, req: CompareRequest) -> Dict[str, Any]:
        if len(req.run_ids) < 2:
            raise HTTPException(status_code=400, detail="Provide at least 2 run IDs")
        _store_for(db_id)
        selections = [(db_id, run_id) for run_id in req.run_ids]
        return await _build_comparison(selections, registry, engine)

    @db_router.get("/runs/{run_id}/metrics")
    async def get_run_metrics(db_id: str, run_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        agg = await engine.aggregate(run_id, store)
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
            meta = row.get("query_metadata") or {}
            seg_val = meta.get(field)
            if seg_val is None:
                continue
            key = (str(seg_val), row["pipeline_id"], row["stage_index"], row["metric_name"], row["k"])
            groups[key].append(row["value"])

        result: Dict[str, Any] = {}
        for (seg_val, pipeline_id, stage_index, metric_name, k), scores in groups.items():
            arr = np.array(scores)
            ci_low, ci_high = bootstrap_ci(scores)
            metric_key = f"{pipeline_id}|stage{stage_index}|{metric_name}@{k}"
            result.setdefault(seg_val, {})[metric_key] = {
                "pipeline_id": pipeline_id,
                "stage_index": stage_index,
                "metric_name": metric_name,
                "k": k,
                "mean": float(arr.mean()),
                "std": float(arr.std()),
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

        items = []
        all_qids = sorted(set(actual_by_id) | set(predicted_by_id) | set(text_by_id))
        for qid in all_qids:
            actual_bucket = actual_by_id.get(qid, "unknown")
            actual_class = to_training_class(actual_bucket) or "unknown"
            pred_info = predicted_by_id.get(qid, {})
            predicted = pred_info.get("predicted_difficulty")
            agreement = _difficulty_agreement(actual_class, predicted)
            items.append({
                "query_id": qid,
                "query_text": text_by_id.get(qid, ""),
                "actual_bucket": actual_bucket,
                "actual_class": actual_class,
                "predicted_difficulty": predicted,
                "predicted_difficulty_proba": pred_info.get("predicted_difficulty_proba"),
                "agreement": agreement,
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

        query_mean_recall = {
            qid: float(np.mean(vals)) for qid, vals in per_query_recall.items() if vals
        }

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
                    "mean_recall10": float(np.mean(scores_pred)),
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
                    "mean_recall10": float(np.mean(scores_actual)),
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
        store = _store_for(db_id)
        runs = [run for run in await store.list_runs() if run["run_id"] == run_id]
        if not runs:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        metrics = await engine.aggregate(run_id, store)
        metrics_rows = await store.get_metrics(run_id)
        diagnostics = await store.get_query_diagnostics(run_id)
        manifest = await store.get_run_manifest(run_id)
        best = _headline_winner(metrics)
        return {
            "run": runs[0],
            "headline_winner": best,
            "diagnostics": aggregate_diagnostics(diagnostics),
            "manifest": manifest,
            "warnings": _overview_warnings(metrics, diagnostics, manifest),
            "stage_contributions": _compute_stage_contributions(metrics, metrics_rows),
        }

    @db_router.get("/runs/{run_id}/queries/{query_id}")
    async def get_query_result(db_id: str, run_id: str, query_id: str) -> Dict[str, Any]:
        store = _store_for(db_id)
        results = [r for r in await store.get_results(run_id) if r.query_id == query_id]
        diagnostics = await store.get_query_diagnostics(run_id, query_id=query_id)
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
            "pipelines": [
                {
                    "pipeline_id": row.pipeline_id,
                    "stage_index": row.stage_index,
                    "label": row.pipeline_id,
                    "metrics": row.metrics,
                    "is_pareto_optimal": row.is_pareto_optimal,
                    "dominated_by": row.dominated_by,
                }
                for row in result.pipelines
            ],
            "frontier_order": result.frontier_order,
        }

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

    # Serve React UI static files if built
    if os.path.exists(_UI_DIST):
        from fastapi.staticfiles import StaticFiles
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
        pid = value.get("pipeline_id")
        sidx = value.get("stage_index", -1)
        if pid and sidx >= 0:
            final_stage_by_pipeline[pid] = max(final_stage_by_pipeline.get(pid, -1), sidx)

    candidates = [
        {"metric": key, **value}
        for key, value in metrics.items()
        if value.get("stage_index", -1) >= 0
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
    if any(value.get("metric_name") == "failure_rate" and value.get("mean", 0.0) > 0 for value in metrics.values()):
        warnings.append("At least one pipeline had failed or timed-out queries.")
    if any("id_or_qrel_issue" in row.get("failure_labels", []) for row in diagnostics):
        warnings.append("Some queries look like possible document ID or qrel mismatches.")
    if manifest and manifest.get("dataset", {}).get("missing_qrel_doc_ids", 0):
        warnings.append("Some qrel document IDs were missing from the loaded corpus.")
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
    """Return raw stage deltas for each adjacent pipeline pair — no pre-computed verdict."""
    pipeline_ids = list({v.get("pipeline_id") for v in metrics.values() if v.get("pipeline_id")})
    pairs = pipeline_pairs(pipeline_ids)
    if not pairs:
        return []

    # Parse keys into {pid: {sidx: [(mname, k, full_key)]}}
    keys_by_pipeline: Dict = {}
    for key, v in metrics.items():
        try:
            pid, sidx, mname, k = parse_metric_key(key)
        except Exception:
            continue
        keys_by_pipeline.setdefault(pid, {}).setdefault(sidx, []).append((mname, k, key))

    quality_metrics = {"recall", "ndcg", "mrr", "map"}
    contributions = []

    for before_id, after_id in pairs:
        before_stages = keys_by_pipeline.get(before_id, {})
        after_stages = keys_by_pipeline.get(after_id, {})
        if not before_stages or not after_stages:
            continue

        before_last = max(s for s in before_stages if s >= 0)
        after_last = max(s for s in after_stages if s >= 0)

        before_quality = {(mname, k): fk for mname, k, fk in before_stages.get(before_last, []) if mname in quality_metrics}
        after_quality = {(mname, k): fk for mname, k, fk in after_stages.get(after_last, []) if mname in quality_metrics}

        deltas: Dict = {}
        raw_p_values: List[float] = []
        delta_p_map: List[tuple] = []

        for mk in sorted(set(before_quality) & set(after_quality)):
            mname, k = mk
            b_mean = metrics[before_quality[mk]]["mean"]
            a_mean = metrics[after_quality[mk]]["mean"]
            absolute = a_mean - b_mean
            pct = (absolute / b_mean * 100) if b_mean != 0 else 0.0

            b_scores = {r["query_id"]: r["value"] for r in metrics_rows
                        if r["pipeline_id"] == before_id and r["stage_index"] == before_last
                        and r["metric_name"] == mname and r["k"] == k}
            a_scores = {r["query_id"]: r["value"] for r in metrics_rows
                        if r["pipeline_id"] == after_id and r["stage_index"] == after_last
                        and r["metric_name"] == mname and r["k"] == k}
            shared = sorted(set(b_scores) & set(a_scores))
            p = None
            if shared:
                p = paired_bootstrap_test([b_scores[q] for q in shared], [a_scores[q] for q in shared])
                raw_p_values.append(p)
            delta_p_map.append((mname, k, b_mean, a_mean, absolute, pct, p))

        q_values = benjamini_hochberg(raw_p_values)
        q_idx = 0
        for mname, k, b_mean, a_mean, absolute, pct, p in delta_p_map:
            label = f"{mname}@{k}" if k > 0 else mname
            q_value = None
            if p is not None:
                q_value = q_values[q_idx]
                q_idx += 1
            deltas[label] = {
                "before": b_mean,
                "after": a_mean,
                "absolute": absolute,
                "pct": pct,
                "q_value": q_value,
                "significant": (q_value is not None and q_value < 0.05),
            }

        # Latency P50
        def _lat(stages):
            sidx = -1 if -1 in stages else max((s for s in stages if s >= 0), default=None)
            if sidx is None:
                return None
            for mname, k, fk in stages.get(sidx, []):
                if mname == "latency_p50" and fk in metrics:
                    return metrics[fk]["mean"]
            return None

        lat_before = _lat(before_stages)
        lat_after = _lat(after_stages)

        contributions.append({
            "from_pipeline": before_id,
            "to_pipeline": after_id,
            "deltas": deltas,
            "latency_p50_before_ms": lat_before,
            "latency_p50_after_ms": lat_after,
            "latency_delta_ms": (lat_after - lat_before) if lat_before is not None and lat_after is not None else None,
        })

    return contributions


def _pipeline_cost_per_1k(config: Dict[str, Any], pipeline_id: str, costs: Dict[str, Dict[str, float]]) -> float:
    from retrieval_observatory.config.cost import pipeline_cost_per_1k

    return pipeline_cost_per_1k(config, pipeline_id, costs)


def _extract_final_stage_metrics(agg: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Return per-pipeline final-stage metrics needed for Pareto analysis."""
    by_pipeline: Dict[str, Dict[int, Dict[tuple, float]]] = defaultdict(lambda: defaultdict(dict))
    for value in agg.values():
        stage_index = value.get("stage_index", -1)
        if stage_index < 0:
            continue
        metric_key = (value["metric_name"], value.get("k", 0))
        by_pipeline[value["pipeline_id"]][stage_index][metric_key] = value["mean"]

    required = {
        ("ndcg", 10): "ndcg10",
        ("recall", 10): "recall10",
        ("latency_p50", 0): "latency_p50",
        ("latency_p95", 0): "latency_p95",
    }

    final_metrics: Dict[str, Dict[str, float | int]] = {}
    for pipeline_id, stages in by_pipeline.items():
        final_stage = max(stages.keys())
        stage_metrics = stages[final_stage]
        row: Dict[str, float | int] = {"stage_index": final_stage}
        complete = True
        for metric_key, field in required.items():
            if metric_key not in stage_metrics:
                complete = False
                break
            row[field] = stage_metrics[metric_key]
        if complete:
            final_metrics[pipeline_id] = row
    return final_metrics
