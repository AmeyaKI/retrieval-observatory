import pytest

from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.runner.benchmark import BenchmarkRunner
from retrieval_observatory.runner.cache import ResultCache
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, Query, RetrievalResult


class FixedRetriever:
    def __init__(self, retriever_id: str, doc_ids: list):
        self.retriever_id = retriever_id
        self._doc_ids = doc_ids

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [Document(id=did, text="", score=1.0, rank=i + 1) for i, did in enumerate(self._doc_ids)]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id=self.retriever_id)


@pytest.mark.asyncio
async def test_traces_v2_do_not_collide_across_runs_with_same_query_and_pipeline(tmp_path):
    """Regression test: traces_v2 rows are keyed by trace_id alone (INSERT OR REPLACE, not
    scoped by run_id in the primary key). Before the fix, lift_pipeline_result derived
    trace_id purely from query_id+pipeline_id, so re-running the same experiment (same
    query_ids, same pipeline_ids -- the entire point of a baseline-vs-candidate comparison)
    silently overwrote the earlier run's trace data. Confirms both runs keep their own,
    distinct traces_v2 rows.
    """
    store = SQLiteStore(db_path=str(tmp_path / "test.db"))
    await store.init_db()
    await store.save_run("run_baseline", "test", "{}")
    await store.save_run("run_candidate", "test", "{}")

    queries = [Query(text="q1", k=2, query_id="q1")]

    runner = BenchmarkRunner(store=store, concurrency=1, timeout_ms=5000)
    pipeline_a = SingleStagePipeline("p1", FixedRetriever("r1", ["d1", "d2"]))
    await runner.run(pipelines=[pipeline_a], queries=queries, run_id="run_baseline")

    pipeline_b = SingleStagePipeline("p1", FixedRetriever("r1", ["d3", "d4"]))
    await runner.run(pipelines=[pipeline_b], queries=queries, run_id="run_candidate")

    baseline_traces = await store.get_traces_v2("run_baseline")
    candidate_traces = await store.get_traces_v2("run_candidate")

    assert len(baseline_traces) == 1
    assert len(candidate_traces) == 1
    assert baseline_traces[0].trace_id != candidate_traces[0].trace_id
    assert baseline_traces[0].run_id == "run_baseline"
    assert candidate_traces[0].run_id == "run_candidate"

    baseline_docs = [c.doc_id for c in baseline_traces[0].spans[-1].outputs]
    candidate_docs = [c.doc_id for c in candidate_traces[0].spans[-1].outputs]
    assert baseline_docs == ["d1", "d2"]
    assert candidate_docs == ["d3", "d4"]


@pytest.mark.asyncio
async def test_cached_result_gets_fresh_trace_id_for_new_run(tmp_path):
    """A cache hit returns a PipelineResult (with its trace_v2 already populated and
    persisted under the run that produced it). Re-running the same query/pipeline under a
    different run_id and serving it from cache must not reuse that stale trace_id."""
    store = SQLiteStore(db_path=str(tmp_path / "test.db"))
    await store.init_db()
    await store.save_run("run_a", "test", "{}")
    await store.save_run("run_b", "test", "{}")

    queries = [Query(text="q1", k=2, query_id="q1")]
    pipeline = SingleStagePipeline("p1", FixedRetriever("r1", ["d1", "d2"]))
    cache = ResultCache(store=store, pipeline_config_yaml="p1-config")

    runner = BenchmarkRunner(store=store, concurrency=1, timeout_ms=5000, caches={"p1": cache})
    await runner.run(pipelines=[pipeline], queries=queries, run_id="run_a")
    await runner.run(pipelines=[pipeline], queries=queries, run_id="run_b")

    traces_a = await store.get_traces_v2("run_a")
    traces_b = await store.get_traces_v2("run_b")
    assert len(traces_a) == 1
    assert len(traces_b) == 1
    assert traces_a[0].trace_id != traces_b[0].trace_id
