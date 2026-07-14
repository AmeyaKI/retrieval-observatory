"""Integration test for retobs demo end-to-end."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from retrieval_observatory.advisor.regression import detect_regressions
from retrieval_observatory.cli import _demo
from retrieval_observatory.store.sqlite import SQLiteStore


@pytest.mark.asyncio
@pytest.mark.slow
async def test_demo_builds_full_reliability_platform(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo_out"
    db_path = str(tmp_path / "results.db")

    await _demo(
        output_dir=str(out_dir),
        db_path=db_path,
        tracelens_service="demo",
        n_traces=30,
        keep_db=False,
        full=False,
    )

    store = SQLiteStore(db_path=db_path)
    await store.init_db()

    runs = await store.list_runs()
    assert len(runs) >= 2

    manifest_path = out_dir / "demo_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline_id = manifest["baseline_run_id"]
    candidate_id = manifest["candidate_run_id"]
    validation_id = manifest["validation_run_id"]
    sample_query_id = manifest["sample_query_id"]

    run_ids = {r["run_id"] for r in runs}
    assert baseline_id in run_ids
    assert candidate_id in run_ids
    assert validation_id in run_ids

    datasets = await store.get_forge_datasets()
    assert any(d.get("dataset_id") == "demo" for d in datasets)

    traces = await store.list_traces(service="demo", limit=1000)
    assert len(traces) == 30

    findings = await detect_regressions(baseline_id, candidate_id, store)
    assert len(findings) >= 1

    lineage = await store.get_query_lineage(sample_query_id)
    assert lineage["origin"]["source"] == "forge"
    assert len(lineage["evaluations"]) >= 3
    assert len(lineage["production_matches"]["traces"]) >= 1

    snapshots = await store.get_reliability_history(limit=10)
    assert len(snapshots) >= 3
