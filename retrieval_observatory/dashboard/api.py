from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import defaultdict
from typing import Any, Dict, List

import numpy as np

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.comparison import paired_scores_by_query, pipeline_pairs, parse_metric_key
from retrieval_observatory.metrics.diagnostics import aggregate_diagnostics
from retrieval_observatory.metrics.significance import benjamini_hochberg, bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.store.sqlite import SQLiteStore

_UI_DIST = os.path.join(os.path.dirname(__file__), "ui", "dist")

try:
    from pydantic import BaseModel as _BaseModel

    class CompareRequest(_BaseModel):
        run_ids: List[str]
except ImportError:
    CompareRequest = None  # type: ignore


def create_app(db_path: str = ".retobs/results.db"):
    try:
        from fastapi import FastAPI, File, HTTPException, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError as e:
        raise ImportError("Dashboard requires fastapi. Install with: pip install fastapi") from e

    app = FastAPI(title="Retrieval Observatory", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = SQLiteStore(db_path=db_path)
    engine = MetricsEngine()

    @app.on_event("startup")
    async def startup():
        await store.init_db()

    @app.get("/runs")
    async def list_runs() -> List[Dict]:
        return await store.list_runs()

    @app.get("/runs/{run_id}/metrics")
    async def get_run_metrics(run_id: str) -> Dict[str, Any]:
        agg = await engine.aggregate(run_id, store)
        if not agg:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or has no metrics")
        return agg

    @app.post("/compare")
    async def compare_runs(req: CompareRequest) -> Dict[str, Any]:
        if len(req.run_ids) < 2:
            raise HTTPException(status_code=400, detail="Provide at least 2 run IDs")

        from collections import defaultdict
        result: Dict[str, Any] = {}

        aggregated = {}
        raw_scores = {}
        for run_id in req.run_ids:
            aggregated[run_id] = await engine.aggregate(run_id, store)
            metrics = await store.get_metrics(run_id)
            scores: dict = defaultdict(list)
            for row in metrics:
                key = f"{row['pipeline_id']}|stage{row['stage_index']}|{row['metric_name']}@{row['k']}"
                scores[key].append(row["value"])
            raw_scores[run_id] = dict(scores)

        all_keys = sorted(set().union(*(agg.keys() for agg in aggregated.values())))
        comparison = []
        for key in all_keys:
            entry: Dict[str, Any] = {"metric": key}
            for run_id in req.run_ids:
                agg = aggregated[run_id].get(key, {})
                entry[run_id] = {
                    "mean": agg.get("mean"),
                    "std": agg.get("std"),
                    "ci_low": agg.get("ci_low"),
                    "ci_high": agg.get("ci_high"),
                }
            # Pairwise significance for first two runs, joined by query_id.
            metrics_1 = await store.get_metrics(req.run_ids[0])
            metrics_2 = await store.get_metrics(req.run_ids[1])
            s1, s2, n_pairs = paired_scores_by_query(metrics_1, metrics_2, key)
            if s1 and s2:
                try:
                    entry["p_value"] = paired_bootstrap_test(s1, s2)
                    entry["paired_n"] = n_pairs
                except Exception:
                    # Keep comparison available even when one metric key has invalid score arrays.
                    pass
            comparison.append(entry)

        return {"comparison": comparison, "run_ids": req.run_ids}

    @app.get("/runs/{run_id}/metrics/by-segment")
    async def get_run_metrics_by_segment(run_id: str, field: str = "n_relevant") -> Dict[str, Any]:
        """Return per-segment aggregated metrics for a run.

        Groups metric_scores rows by a query metadata field (e.g. 'n_relevant').
        Returns {segment_value: {metric_key: {mean, std, ci_low, ci_high, n}}}.
        """
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

    @app.get("/runs/{run_id}/manifest")
    async def get_manifest(run_id: str) -> Dict[str, Any]:
        manifest = await store.get_run_manifest(run_id)
        if not manifest:
            raise HTTPException(status_code=404, detail=f"No manifest for run '{run_id}'")
        return manifest

    @app.get("/runs/{run_id}/diagnostics")
    async def get_diagnostics(run_id: str) -> Dict[str, Any]:
        rows = await store.get_query_diagnostics(run_id)
        return {"summary": aggregate_diagnostics(rows), "items": rows}

    @app.get("/runs/{run_id}/overview")
    async def get_run_overview(run_id: str) -> Dict[str, Any]:
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

    @app.get("/runs/{run_id}/queries/{query_id}")
    async def get_query_result(run_id: str, query_id: str) -> Dict[str, Any]:
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

    @app.get("/runs/{run_id}/stage-matrix")
    async def get_stage_matrix(run_id: str) -> Dict[str, Any]:
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
            await store.save_validation_report(report, config_path=config_file.filename)
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
    except ImportError:
        @app.post("/validate")
        async def validate_upload_unavailable() -> Dict[str, Any]:
            raise HTTPException(status_code=501, detail="Install retrieval-observatory[dashboard] with python-multipart to use upload validation.")

        @app.post("/experiments/prepare")
        async def prepare_upload_unavailable() -> Dict[str, Any]:
            raise HTTPException(status_code=501, detail="Install retrieval-observatory[dashboard] with python-multipart to use experiment uploads.")

    # Serve React UI static files if built
    if os.path.exists(_UI_DIST):
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        assets_dir = os.path.join(_UI_DIST, "assets")
        if os.path.exists(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        _index = os.path.join(_UI_DIST, "index.html")

        @app.get("/", include_in_schema=False)
        async def spa_root():
            return FileResponse(_index)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            return FileResponse(_index)

    return app


def _headline_winner(metrics: Dict[str, Any]) -> Dict[str, Any] | None:
    candidates = [
        {"metric": key, **value}
        for key, value in metrics.items()
        if value.get("metric_name") in {"ndcg", "recall"} and value.get("k") in {10, 20}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row.get("mean", 0.0))


def _overview_warnings(metrics: Dict[str, Any], diagnostics: List[Dict], manifest: Dict | None) -> List[str]:
    warnings = []
    if any(value.get("metric_name") == "failure_rate" and value.get("mean", 0.0) > 0 for value in metrics.values()):
        warnings.append("At least one pipeline had failed or timed-out queries.")
    if any("id_or_qrel_issue" in row.get("failure_labels", []) for row in diagnostics):
        warnings.append("Some queries look like possible document ID or qrel mismatches.")
    if manifest and manifest.get("dataset", {}).get("missing_qrel_doc_ids", 0):
        warnings.append("Some qrel document IDs were missing from the loaded corpus.")
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
    pipeline = next((p for p in config.get("pipelines", []) if p.get("id") == pipeline_id), None)
    if not pipeline:
        return 0.0
    total = 0.0
    for stage in pipeline.get("stages", []):
        stage_id = stage.get("retriever_id") or stage.get("type")
        stage_cost = costs.get(stage_id, costs.get(stage.get("type"), {}))
        total += float(stage_cost.get("per_1k_queries", 0.0))
    return total
