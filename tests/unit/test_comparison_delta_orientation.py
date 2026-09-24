"""query_diffs.delta is candidate minus baseline, matching orientation.effect on /compare."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore

DEMO_DB = Path(os.environ.get("RETOBS_DEMO_DB", Path(__file__).resolve().parents[2] / ".retobs" / "demo" / "results.db"))
BASELINE = {"q1": 0.9, "q2": 0.8, "q3": 0.1, "q4": 0.2}
CANDIDATE = {"q1": 0.0, "q2": 0.2, "q3": 0.3, "q4": 0.4}


def _manifest() -> dict:
    return {
        "schema_version": 3,
        "dataset": {"name": "beir/nfcorpus", "query_hash": "q", "corpus_hash": "c", "qrel_hash": "r"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "execution": {"seed": 1, "cache_results": False, "timeout_ms": 5000},
        "git_commit": "commit",
        "git_dirty": False,
        "models": [{"model": "bm25"}],
        "packages": {"retobs": "test"},
    }


async def _seed(store: SQLiteStore, run_id: str, scores: dict) -> None:
    await store.save_run(run_id, f"exp-{run_id}", json.dumps({"dataset": {"name": "beir/nfcorpus"}}))
    await store.save_run_manifest(run_id, _manifest())
    for query_id, value in scores.items():
        await store.save_metric(run_id, "bm25", query_id, 0, "ndcg", 10, value)
    await store.finish_run(run_id)


@pytest.mark.asyncio
async def test_query_diffs_delta_is_candidate_minus_baseline(tmp_path: Path) -> None:
    store = SQLiteStore(str(tmp_path / "cmp.db"))
    await store.init_db()
    await _seed(store, "base", BASELINE)
    await _seed(store, "cand", CANDIDATE)
    registry = DbRegistry([str(tmp_path / "cmp.db")])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db = registry.default_db_id
    body = client.post(
        "/compare",
        json={"selections": [{"db_id": db, "run_id": "base", "role": "baseline"}, {"db_id": db, "run_id": "cand", "role": "candidate"}]},
    ).json()
    assert body["orientation"]["effect"] == "candidate_minus_baseline"
    diffs = body["query_diffs"]
    assert diffs["orientation"]["effect"] == "candidate_minus_baseline"
    assert diffs["orientation"]["baseline"] == {"db_id": db, "run_id": "base"}
    assert diffs["orientation"]["candidate"] == {"db_id": db, "run_id": "cand"}
    rows = {row["query_id"]: row for row in diffs["rows"]}
    assert rows["q1"]["a"] == pytest.approx(0.9) and rows["q1"]["b"] == pytest.approx(0.0)
    assert rows["q1"]["delta"] == pytest.approx(-0.9)
    assert rows["q3"]["delta"] == pytest.approx(0.2)
    # Sorted by |delta| descending, and the per-query deltas average to the paired effect.
    assert [row["query_id"] for row in diffs["rows"]][:2] == ["q1", "q2"]
    entry = next(item for item in body["comparison"] if item["metric"] == diffs["metric"])
    mean_delta = sum(row["delta"] for row in diffs["rows"]) / len(diffs["rows"])
    assert mean_delta == pytest.approx(entry["statistics"]["effect"])
    # The diff route names the baseline run and its database.
    template = body["release_decision"]["investigation"]["diff_route_template"]
    assert template.startswith("#/investigate?db=cmp&run=cand") and template.endswith("query={query_id}&compare=base")
    assert f"db={db}" in template


@pytest.mark.skipif(not (DEMO_DB.parent / "demo_manifest.json").is_file(), reason="`retobs demo` output not present")
def test_demo_validation_run_recovers_the_lost_document_query() -> None:
    """On `retobs demo` output the repaired run is the candidate: q-outage's delta is positive."""
    manifest = json.loads((DEMO_DB.parent / "demo_manifest.json").read_text(encoding="utf-8"))
    baseline, validation = manifest["baseline_run_id"], manifest["validation_run_id"]
    registry = DbRegistry([str(DEMO_DB)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db = registry.default_db_id
    body = client.post(
        "/compare",
        json={"selections": [{"db_id": db, "run_id": baseline, "role": "baseline"}, {"db_id": db, "run_id": validation, "role": "candidate"}]},
    ).json()
    diffs = body["query_diffs"]
    assert diffs["orientation"]["baseline"] == {"db_id": db, "run_id": baseline}
    assert diffs["orientation"]["candidate"] == {"db_id": db, "run_id": validation}
    top = diffs["rows"][0]
    assert top["query_id"] == manifest["sample_query_id"] == "q-outage"
    assert top["a"] == pytest.approx(0.0) and top["delta"] > 0
    entry = next(item for item in body["comparison"] if item["metric"] == diffs["metric"])
    assert entry["statistics"]["effect"] > 0
    assert sum(row["delta"] for row in diffs["rows"]) / len(diffs["rows"]) == pytest.approx(entry["statistics"]["effect"])
