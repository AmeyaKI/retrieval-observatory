from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


async def _seed_run(db_path: Path, run_id: str, dataset_name: str) -> None:
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    await store.save_run(run_id, f"exp-{run_id}", json.dumps({"dataset": {"name": dataset_name}}))
    manifest = {
        "schema_version": 3,
        "dataset": {
            "name": dataset_name,
            "query_hash": f"queries:{dataset_name}",
            "corpus_hash": f"corpus:{dataset_name}",
            "qrel_hash": f"qrels:{dataset_name}",
        },
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "execution": {"seed": 1, "cache_results": False, "timeout_ms": 5000},
        "git_commit": "commit",
        "git_dirty": False,
        "models": [{"model": "bm25"}],
        "packages": {"retobs": "test"},
    }
    await store.save_run_manifest(run_id, manifest)
    await store.save_metric(
        run_id=run_id,
        pipeline_id="bm25",
        query_id="q1",
        stage_index=0,
        metric_name="recall",
        k=10,
        value=0.5,
    )
    await store.finish_run(run_id)


@pytest.fixture
async def two_db_registry(tmp_path: Path) -> DbRegistry:
    db_a = tmp_path / "nfcorpus.db"
    db_b = tmp_path / "scifact.db"
    await _seed_run(db_a, "aaaaaaaa", "beir/nfcorpus")
    await _seed_run(db_b, "bbbbbbbb", "beir/scifact")
    return DbRegistry([str(db_a), str(db_b)])


@pytest.mark.asyncio
async def test_list_dbs_and_scoped_runs(two_db_registry: DbRegistry) -> None:
    app = create_app(registry=two_db_registry, enable_uploads=False)
    client = TestClient(app)

    dbs = client.get("/dbs").json()
    assert len(dbs) == 2
    db_ids = {d["db_id"] for d in dbs}
    assert "nfcorpus" in db_ids
    assert "scifact" in db_ids

    runs = client.get(f"/dbs/{dbs[0]['db_id']}/runs").json()
    assert len(runs) == 1
    assert runs[0]["db_id"] == dbs[0]["db_id"]


@pytest.mark.asyncio
async def test_cross_db_compare_warns_on_different_datasets(two_db_registry: DbRegistry) -> None:
    app = create_app(registry=two_db_registry, enable_uploads=False)
    client = TestClient(app)
    db_ids = two_db_registry.list_db_ids()

    resp = client.post(
        "/compare",
        json={
            "selections": [
                {"db_id": db_ids[0], "run_id": "aaaaaaaa"},
                {"db_id": db_ids[1], "run_id": "bbbbbbbb"},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["warnings"]
    assert body["comparability"]["outcome"] == "invalid"
    assert body["comparability"]["decision_allowed"] is False
    assert "comparison" in body
    assert body["comparison"]
    assert body["release_decision"]["status"] == "HOLD"
    assert body["release_decision"]["policy"]["configured"] is False


@pytest.mark.asyncio
async def test_legacy_single_db_runs_alias(tmp_path: Path) -> None:
    db_path = tmp_path / "solo.db"
    await _seed_run(db_path, "cccccccc", "beir/nfcorpus")
    registry = DbRegistry([str(db_path)])
    app = create_app(registry=registry, enable_uploads=False)
    client = TestClient(app)

    runs = client.get("/runs").json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "cccccccc"


@pytest.mark.asyncio
async def test_lineage_endpoint_is_database_scoped(tmp_path: Path) -> None:
    db_a = tmp_path / "first.db"
    db_b = tmp_path / "second.db"
    await _seed_run(db_a, "run-a", "first")
    await _seed_run(db_b, "run-a", "second")
    first_store = SQLiteStore(db_path=str(db_a))
    await first_store.init_db()
    candidate = Candidate(
        "doc-1", 1.0, 1, candidate_id="candidate-1", logical_chunk_id="chunk-1"
    )
    await first_store.save_trace(
        RetrievalTrace(
            trace_id="first-trace",
            service_id="search",
            run_id="run-a",
            query_id="q-1",
            query_text="private",
            pipeline_id="pipeline",
            spans=(OperatorSpan.source("retrieve", "retrieve", (candidate,)),),
            final_op_ids=("retrieve",),
        )
    )
    registry = DbRegistry([str(db_a), str(db_b)])
    db_ids = registry.list_db_ids()
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    first = client.get(
        f"/dbs/{db_ids[0]}/runs/run-a/queries/q-1/candidate-lineage"
    )
    second = client.get(
        f"/dbs/{db_ids[1]}/runs/run-a/queries/q-1/candidate-lineage"
    )

    assert first.status_code == 200
    assert first.json()["traces"][0]["trace_id"] == "first-trace"
    assert second.status_code == 404
