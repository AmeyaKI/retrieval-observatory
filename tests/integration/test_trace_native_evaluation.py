from __future__ import annotations

import pytest

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.runner.benchmark import BenchmarkRunner
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, Query, RetrievalResult


class _Retriever:
    retriever_id = "source"

    def retrieve(self, query: Query) -> RetrievalResult:
        return RetrievalResult([Document("gold", "", 1.0, 1)], 1.0, self.retriever_id)


@pytest.mark.asyncio
async def test_evaluation_persists_trace_before_metrics(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "evaluation.db"))
    await store.init_db()
    await store.save_run("run", "evaluation", "{}")
    runner = BenchmarkRunner(store, concurrency=1)
    results = await runner.run(
        [SingleStagePipeline("pipeline", _Retriever())],
        [Query("query", query_id="q1")],
        "run",
    )
    traces = await store.list_traces(TraceQuery(run_id="run"))
    assert len(traces) == 1
    assert results["pipeline"][0].trace is traces[0] or results["pipeline"][0].trace.to_dict() == traces[0].to_dict()

    engine = MetricsEngine(recall_at_k_values=[1], precision_at_k_values=[1], ndcg_at_k_values=[1])
    await engine.compute_from_traces("run", store, traces, {"q1": {"gold": 1}})
    assert any(row["metric_name"] == "recall" for row in await store.get_metrics("run"))
