"""Hot-path behaviour: the aggregate LRU is keyed by metric-row count, the per-query result
loads only that query's traces, and /diagram projects the pipeline graph once."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline import graph_projection
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

RUN = "run1"


def _trace(query_id: str) -> RetrievalTrace:
    source = OperatorSpan(
        "source", "SOURCE", "source", (), "FIRED", 2.0,
        outputs=(Candidate(doc_id="d1", score=1.0, rank=1),), replay_policy="EXACT",
    )
    return RetrievalTrace(
        trace_id=f"t-{query_id}", service_id="bench", run_id=RUN, query_id=query_id, query_text="q",
        pipeline_id="bm25", spans=(source,), final_op_ids=("source",),
        timing=TraceTiming(wall_clock_ms=2.0, critical_path_ms=2.0, operator_sum_ms=2.0),
    )


@pytest.fixture
async def registry(tmp_path: Path) -> DbRegistry:
    db_path = tmp_path / "perf.db"
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run(RUN, "perf", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_qrels(RUN, {f"q{i}": {"d1": 1} for i in range(4)})
    await store.save_traces([_trace(f"q{i}") for i in range(4)])
    for i in range(4):
        await store.save_metric(RUN, "bm25", f"q{i}", 0, "recall", 10, 1.0)
        await store.save_metric(RUN, "bm25", f"q{i}", 0, "ndcg", 10, 1.0)
        await store.save_metric(RUN, "bm25", f"q{i}", 0, "latency_ms", 0, 2.0)
    await store.finish_run(RUN)
    return DbRegistry([str(db_path)])


@pytest.mark.asyncio
async def test_aggregate_is_memoised_until_metric_rows_change(registry: DbRegistry, monkeypatch) -> None:
    calls = {"n": 0}
    real = MetricsEngine.aggregate

    async def counting(self, run_id, store, n_bootstrap=1000):
        calls["n"] += 1
        return await real(self, run_id, store, n_bootstrap)

    monkeypatch.setattr(MetricsEngine, "aggregate", counting)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    db = registry.default_db_id
    for path in ("overview", "stage-matrix", "pareto-frontier", "metrics", "overview"):
        assert client.get(f"/dbs/{db}/runs/{RUN}/{path}").status_code == 200
    assert calls["n"] == 1, "one aggregate should serve every run page"
    # Appending metric rows changes the fingerprint and busts the entry.
    await registry.get_store(db).save_metric(RUN, "bm25", "q9", 0, "recall", 10, 0.0)
    assert client.get(f"/dbs/{db}/runs/{RUN}/overview").status_code == 200
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_query_result_loads_only_that_query(registry: DbRegistry, monkeypatch) -> None:
    store = registry.get_store(registry.default_db_id)
    seen: list[TraceQuery] = []
    real = store.list_traces

    async def recording(query=None, **kwargs):
        seen.append(query)
        return await real(query, **kwargs)

    monkeypatch.setattr(store, "list_traces", recording)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    body = client.get(f"/dbs/{registry.default_db_id}/runs/{RUN}/queries/q2").json()
    assert [r["pipeline_id"] for r in body["results"]] == ["bm25"]
    assert seen and all(q is not None and q.query_id == "q2" for q in seen), seen


@pytest.mark.asyncio
async def test_diagram_projects_the_graph_once(registry: DbRegistry, monkeypatch) -> None:
    calls = {"graphs": 0, "traces": 0}
    real_build = graph_projection.build_pipeline_graphs

    def counting_build(*args, **kwargs):
        calls["graphs"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(graph_projection, "build_pipeline_graphs", counting_build)
    store = registry.get_store(registry.default_db_id)
    real_list = store.list_traces

    async def counting_list(query=None, **kwargs):
        calls["traces"] += 1
        return await real_list(query, **kwargs)

    monkeypatch.setattr(store, "list_traces", counting_list)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    body = client.get(f"/dbs/{registry.default_db_id}/runs/{RUN}/diagram").json()
    assert body["pipelines"] and body["operator_dag"]["nodes"]
    assert calls == {"graphs": 1, "traces": 1}
