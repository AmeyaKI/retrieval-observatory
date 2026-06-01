#!/usr/bin/env python3
"""Export a benchmark run from SQLite to results/{dataset}/ artifacts."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from retrieval_observatory.dashboard.api import _compute_stage_contributions
from retrieval_observatory.metrics.diagnostics import aggregate_diagnostics
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.store.sqlite import SQLiteStore


async def _latest_run_id(store: SQLiteStore) -> str:
    runs = await store.list_runs()
    if not runs:
        raise SystemExit("No runs in database")
    return runs[0]["run_id"]


async def export_run(db_path: str, run_id: str, out_dir: Path) -> None:
    store = SQLiteStore(db_path=db_path)
    engine = MetricsEngine()
    aggregated = await engine.aggregate(run_id, store)
    metrics_rows = await store.get_metrics(run_id)
    diagnostics_rows = await store.get_query_diagnostics(run_id)
    runs = await store.list_runs()
    run = next((r for r in runs if r.get("run_id") == run_id), None)

    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "metrics.json", "w") as f:
        json.dump(aggregated, f, indent=2)

    diag = aggregate_diagnostics(diagnostics_rows)
    with open(out_dir / "diagnostics.json", "w") as f:
        json.dump(diag, f, indent=2)

    contributions = _compute_stage_contributions(aggregated, metrics_rows)
    with open(out_dir / "stage_contributions.json", "w") as f:
        json.dump(contributions, f, indent=2)

    meta = {
        "run_id": run_id,
        "experiment_name": (run or {}).get("experiment_name"),
        "db_path": db_path,
    }
    with open(out_dir / "run_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Exported run {run_id} -> {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export retobs SQLite run to results/")
    parser.add_argument("--db", required=True, help="SQLite db path (e.g. .retobs/publish_smoke_nfcorpus.db)")
    parser.add_argument("--run-id", default=None, help="Run ID (default: latest in db)")
    parser.add_argument("--out-dir", required=True, help="Output directory (e.g. results/nfcorpus)")
    args = parser.parse_args()

    async def _main() -> None:
        store = SQLiteStore(db_path=args.db)
        run_id = args.run_id or await _latest_run_id(store)
        await export_run(args.db, run_id, Path(args.out_dir))

    asyncio.run(_main())


if __name__ == "__main__":
    main()
