"""Multi-database registry: the demo context names its db_id (and hides paths when read-only),
candidate-lineage-diff can read the baseline from another store, and /compare's diff route
carries the baseline database."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def _manifest(dataset: str) -> dict:
    return {
        "schema_version": 3,
        "dataset": {"name": dataset, "query_hash": "q", "corpus_hash": "c", "qrel_hash": "r"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "execution": {"seed": 1, "cache_results": False, "timeout_ms": 5000},
        "git_commit": "commit",
        "git_dirty": False,
        "models": [{"model": "bm25"}],
        "packages": {"retobs": "test"},
    }


def _trace(run_id: str, query_id: str, doc_ids: tuple) -> RetrievalTrace:
    source = OperatorSpan(
        "source", "SOURCE", "source", (), "FIRED", 2.0,
        outputs=tuple(Candidate(doc_id=d, score=1.0 / (i + 1), rank=i + 1) for i, d in enumerate(doc_ids)),
        replay_policy="EXACT",
    )
    return RetrievalTrace(
        trace_id=f"{run_id}-{query_id}", service_id="bench", run_id=run_id, query_id=query_id, query_text="q",
        pipeline_id="bm25", spans=(source,), final_op_ids=("source",),
        timing=TraceTiming(wall_clock_ms=2.0, critical_path_ms=2.0, operator_sum_ms=2.0),
    )


async def _seed(db_path: Path, run_id: str, doc_ids: tuple, ndcg: float) -> None:
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run(run_id, f"exp-{run_id}", json.dumps({"dataset": {"name": "beir/nfcorpus"}}))
    await store.save_run_manifest(run_id, _manifest("beir/nfcorpus"))
    await store.save_qrels(run_id, {"q1": {"d1": 1}})
    await store.save_traces([_trace(run_id, "q1", doc_ids)])
    await store.save_metric(run_id, "bm25", "q1", 0, "ndcg", 10, ndcg)
    await store.finish_run(run_id)


@pytest.fixture
async def two_dbs(tmp_path: Path) -> tuple[Path, Path]:
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    db_a, db_b = dir_a / "flagship.db", dir_b / "demo.db"
    await _seed(db_a, "aaaaaaaa", ("d1", "d2"), 1.0)
    await _seed(db_b, "bbbbbbbb", ("d2", "d3"), 0.0)
    (dir_b / "demo_manifest.json").write_text(
        json.dumps({"baseline_run_id": "bbbbbbbb", "candidate_run_id": "bbbbbbbb", "sample_query_id": "q1"}),
        encoding="utf-8",
    )
    return db_a, db_b


@pytest.mark.asyncio
async def test_demo_context_names_its_db_id(two_dbs: tuple[Path, Path]) -> None:
    db_a, db_b = two_dbs
    registry = DbRegistry([str(db_a), str(db_b)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    context = client.get("/demo/context").json()
    assert context["baseline_run_id"] == "bbbbbbbb"
    assert context["db_id"] == registry.list_db_ids()[1] == "demo"
    assert context["db_path"] == str(db_b.resolve())


@pytest.mark.asyncio
async def test_demo_context_hides_db_path_when_read_only(two_dbs: tuple[Path, Path]) -> None:
    db_a, db_b = two_dbs
    registry = DbRegistry([str(db_a), str(db_b)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    context = client.get("/demo/context").json()
    assert context["db_id"] == "demo"
    assert "db_path" not in context


@pytest.mark.asyncio
async def test_lineage_diff_reads_baseline_from_against_db(two_dbs: tuple[Path, Path]) -> None:
    db_a, db_b = two_dbs
    registry = DbRegistry([str(db_a), str(db_b)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    flagship, demo = registry.list_db_ids()
    same_db = client.get(f"/dbs/{demo}/runs/bbbbbbbb/queries/q1/candidate-lineage-diff?against=aaaaaaaa")
    assert same_db.status_code == 404, "baseline run lives in the other database"
    cross = client.get(
        f"/dbs/{demo}/runs/bbbbbbbb/queries/q1/candidate-lineage-diff?against=aaaaaaaa&against_db_id={flagship}"
    )
    assert cross.status_code == 200, cross.text
    body = cross.json()
    assert body["baseline_run_id"] == "aaaaaaaa" and body["baseline_db_id"] == flagship
    assert body["candidate_run_id"] == "bbbbbbbb" and body["candidate_db_id"] == demo
    assert len(body["diffs"]) == 1
    unknown = client.get(
        f"/dbs/{demo}/runs/bbbbbbbb/queries/q1/candidate-lineage-diff?against=aaaaaaaa&against_db_id=nope"
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_compare_diff_route_carries_the_baseline_db(two_dbs: tuple[Path, Path]) -> None:
    db_a, db_b = two_dbs
    registry = DbRegistry([str(db_a), str(db_b)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    flagship, demo = registry.list_db_ids()
    body = client.post(
        "/compare",
        json={"selections": [
            {"db_id": flagship, "run_id": "aaaaaaaa", "role": "baseline"},
            {"db_id": demo, "run_id": "bbbbbbbb", "role": "candidate"},
        ]},
    ).json()
    template = body["release_decision"]["investigation"]["diff_route_template"]
    assert template == f"#/investigate?db={demo}&run=bbbbbbbb&view=queries&query={{query_id}}&compare=aaaaaaaa&compare_db={flagship}"
    assert body["query_diffs"]["orientation"]["baseline"]["db_id"] == flagship
