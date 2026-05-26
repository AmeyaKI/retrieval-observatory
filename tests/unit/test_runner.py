import asyncio
from typing import List

import pytest

from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.runner.benchmark import BenchmarkRunner
from retrieval_observatory.runner.scheduler import interleave_tasks
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, Query, RetrievalResult


class FastMockRetriever:
    def __init__(self, retriever_id: str, doc_ids: list):
        self.retriever_id = retriever_id
        self._doc_ids = doc_ids

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [Document(id=did, text="", score=1.0, rank=i + 1) for i, did in enumerate(self._doc_ids)]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id=self.retriever_id)


class SlowRetriever:
    retriever_id = "slow"

    async def retrieve(self, query: Query) -> RetrievalResult:
        await asyncio.sleep(10)  # will trigger timeout
        return RetrievalResult(documents=[], latency_ms=0.0, retriever_id="slow")


def test_interleave_tasks_covers_all():
    tasks = interleave_tasks(["p1", "p2"], ["q1", "q2", "q3"])
    assert len(tasks) == 6
    assert set(tasks) == {("p1", "q1"), ("p1", "q2"), ("p1", "q3"),
                          ("p2", "q1"), ("p2", "q2"), ("p2", "q3")}


def test_interleave_tasks_deterministic_seed():
    t1 = interleave_tasks(["p1", "p2"], ["q1", "q2"], seed=42)
    t2 = interleave_tasks(["p1", "p2"], ["q1", "q2"], seed=42)
    assert t1 == t2


@pytest.mark.asyncio
async def test_runner_stores_all_results(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "test.db"))
    await store.init_db()
    await store.save_run("run1", "test", "{}")

    retriever = FastMockRetriever("r1", ["d1", "d2"])
    pipeline = SingleStagePipeline("p1", retriever)

    queries = [Query(text=f"q{i}", k=2, query_id=f"q{i}") for i in range(5)]

    runner = BenchmarkRunner(store=store, concurrency=3, timeout_ms=5000)
    results = await runner.run(pipelines=[pipeline], queries=queries, run_id="run1")

    assert len(results["p1"]) == 5
    stored = await store.get_results("run1")
    assert len(stored) == 5


@pytest.mark.asyncio
async def test_runner_captures_timeout(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "test.db"))
    await store.init_db()
    await store.save_run("run1", "test", "{}")

    pipeline = SingleStagePipeline("p_slow", SlowRetriever())
    queries = [Query(text="q", k=5, query_id="q1")]

    runner = BenchmarkRunner(store=store, concurrency=1, timeout_ms=100)
    results = await runner.run(pipelines=[pipeline], queries=queries, run_id="run1")

    assert results["p_slow"][0].status == "TIMEOUT"
    stored = await store.get_results("run1")
    assert len(stored) == 1
    assert stored[0].status == "TIMEOUT"
