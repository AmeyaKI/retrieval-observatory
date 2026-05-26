from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any, Dict, List

import numpy as np

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.significance import bootstrap_ci, paired_bootstrap_test
from retrieval_observatory.store.sqlite import SQLiteStore

_UI_DIST = os.path.join(os.path.dirname(__file__), "ui", "dist")


def create_app(db_path: str = ".retobs/results.db"):
    try:
        from fastapi import FastAPI, HTTPException
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

    class CompareRequest(BaseModel):
        run_ids: List[str]

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
            # Pairwise significance for first two runs
            s1 = raw_scores[req.run_ids[0]].get(key, [])
            s2 = raw_scores[req.run_ids[1]].get(key, [])
            if s1 and s2 and len(s1) == len(s2):
                entry["p_value"] = paired_bootstrap_test(s1, s2)
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
