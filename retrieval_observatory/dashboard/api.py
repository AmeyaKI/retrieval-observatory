from __future__ import annotations

import os
from typing import Any, Dict, List

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.significance import paired_bootstrap_test
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
