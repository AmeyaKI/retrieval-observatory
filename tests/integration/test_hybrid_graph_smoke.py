"""Golden-run smoke: hybrid fixture run → pipeline-graph + pareto-frontier invariants."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_hybrid_run_pipeline_graph_and_pareto_smoke(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from retrieval_observatory.dashboard.api import create_app
    from retrieval_observatory.dashboard.registry import DbRegistry
    from retrieval_observatory.sdk import run_from_config

    db_path = str(tmp_path / "hybrid_smoke.db")
    cfg = {
        "experiment": {"name": "hybrid-smoke"},
        "dataset": {
            "type": "custom",
            "name": "custom",
            "queries_path": str(FIXTURES / "tiny_queries.jsonl"),
            "corpus_path": str(FIXTURES / "tiny_corpus.jsonl"),
        },
        "pipelines": [
            {"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]},
            {
                "id": "hybrid",
                "stages": [
                    {
                        "type": "adapter.rrf",
                        "retriever_id": "hybrid_rrf",
                        "config": {
                            "rrf_k": 60,
                            "top_k": 10,
                            "retrievers": [
                                {"type": "adapter.bm25", "retriever_id": "bm25"},
                                {"type": "adapter.bm25", "retriever_id": "bm25_b"},
                            ],
                        },
                    }
                ],
            },
        ],
        "metrics": {"recall_at_k": [10], "ndcg_at_k": [10], "mrr": False, "map": False, "latency_percentiles": [50, 95]},
        "output": {"store": "sqlite", "db_path": db_path},
    }
    report = run_from_config(cfg, max_queries=5)
    run_id = report.run_id

    app = create_app(registry=DbRegistry([db_path]), enable_uploads=False)
    with TestClient(app) as client:
        db_id = client.get("/dbs").json()[0]["db_id"]
        graph = client.get(f"/dbs/{db_id}/runs/{run_id}/pipeline-graph").json()
        assert graph["pipelines"], "expected at least one pipeline graph"
        hybrid = next((g for g in graph["pipelines"] if g["pipeline_id"] == "hybrid"), graph["pipelines"][0])
        fan_in = [e for e in hybrid["edges"] if e["kind"] == "fan_in"]
        assert fan_in, "hybrid fixture should emit fan_in edges into FUSE"
        for node in hybrid["nodes"]:
            for key in ("ndcg@10", "recall", "latency_p50"):
                mv = node["metrics"].get(key)
                if mv and mv.get("mean") is not None and mv.get("ci_low") is not None:
                    assert mv["ci_low"] <= mv["mean"] <= mv["ci_high"]

        pareto = client.get(f"/dbs/{db_id}/runs/{run_id}/pareto-frontier").json()
        assert pareto["pipelines"]
        assert "omitted_pipelines" in pareto
        for row in pareto["pipelines"]:
            m = row["metrics"]
            assert m["latency_p50"] > 0
            if m.get("ndcg@10_ci_low") is not None:
                assert m["ndcg@10_ci_low"] <= m["ndcg@10"] <= m["ndcg@10_ci_high"]

        manifest = client.get(f"/dbs/{db_id}/runs/{run_id}/overview").json()["manifest"]
        assert manifest.get("schema_version") == 3
        assert manifest.get("stage_labels")
