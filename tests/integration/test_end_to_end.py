"""End-to-end integration test using fixture data (no network calls)."""
import os

import pytest

from retrieval_observatory.datasets.custom import CustomDataset
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.runner.benchmark import BenchmarkRunner
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, Query, RetrievalResult

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


class CorpusRetriever:
    """Simple retriever that returns all corpus docs ranked by text match."""

    def __init__(self, corpus: dict):
        self.retriever_id = "corpus_retriever"
        self._corpus = corpus

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [
            Document(
                id=doc_id,
                text=text,
                score=float(query.text.lower() in text.lower()),
                rank=i + 1,
            )
            for i, (doc_id, text) in enumerate(list(self._corpus.items())[: query.k])
        ]
        return RetrievalResult(documents=docs, latency_ms=2.0, retriever_id=self.retriever_id)


@pytest.mark.asyncio
async def test_full_pipeline_with_fixture_data(tmp_path):
    # Load fixture dataset
    dataset = CustomDataset(
        queries_path=os.path.join(FIXTURES, "tiny_queries.jsonl"),
        corpus_path=os.path.join(FIXTURES, "tiny_corpus.jsonl"),
    )
    queries, qrels = dataset.load()
    assert len(queries) == 5
    assert len(qrels) == 5

    # Build pipeline with fixture corpus
    retriever = CorpusRetriever(corpus=dataset.corpus)
    pipeline = SingleStagePipeline(pipeline_id="test_pipeline", retriever=retriever)

    # Set up store
    store = SQLiteStore(db_path=str(tmp_path / "test.db"))
    await store.init_db()
    await store.save_run("run1", "integration-test", "{}")

    # Run benchmark
    runner = BenchmarkRunner(store=store, concurrency=2, timeout_ms=5000)
    results = await runner.run(pipelines=[pipeline], queries=queries, run_id="run1")

    assert len(results["test_pipeline"]) == 5
    assert all(r.status == "OK" for r in results["test_pipeline"])

    # Compute metrics
    engine = MetricsEngine(recall_at_k_values=[1, 5, 10], compute_mrr=True)
    all_results = results["test_pipeline"]
    await engine.compute_and_store(
        run_id="run1",
        store=store,
        results=all_results,
        qrels=qrels,
    )

    # Aggregate and verify structure
    aggregated = await engine.aggregate(run_id="run1", store=store)
    assert len(aggregated) > 0

    from retrieval_observatory.metrics.diagnostics import build_query_diagnostics

    diagnostics = build_query_diagnostics("run1", all_results, qrels)
    await store.save_query_diagnostics(diagnostics)
    stored_diagnostics = await store.get_query_diagnostics("run1")
    assert len(stored_diagnostics) == 5

    # Check that recall metrics exist
    recall_keys = [k for k in aggregated if "recall" in k]
    assert len(recall_keys) > 0

    # Verify mean is in valid range
    for key, vals in aggregated.items():
        if "latency" not in key:
            assert 0.0 <= vals["mean"] <= 1.0, f"{key}: mean={vals['mean']} out of range"
