"""Quickstart: run a benchmark with a mock retriever and fixture data."""
from __future__ import annotations

import asyncio
import os

from retrieval_observatory.datasets.custom import CustomDataset
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.runner.benchmark import BenchmarkRunner
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, Query, RetrievalResult

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")


class MockBM25Retriever:
    """Toy retriever that returns corpus docs in fixed order."""

    retriever_id = "mock_bm25"

    def __init__(self, corpus: dict):
        self._docs = list(corpus.items())

    def retrieve(self, query: Query) -> RetrievalResult:
        docs = [
            Document(id=doc_id, text=text, score=1.0 / (i + 1), rank=i + 1)
            for i, (doc_id, text) in enumerate(self._docs[: query.k])
        ]
        return RetrievalResult(documents=docs, latency_ms=5.0, retriever_id=self.retriever_id)


async def main():
    # Load fixture dataset
    dataset = CustomDataset(
        queries_path=os.path.join(FIXTURES, "tiny_queries.jsonl"),
        corpus_path=os.path.join(FIXTURES, "tiny_corpus.jsonl"),
    )
    queries, qrels = dataset.load()
    print(f"Loaded {len(queries)} queries")

    # Build pipeline
    retriever = MockBM25Retriever(corpus=dataset.corpus)
    pipeline = SingleStagePipeline(pipeline_id="mock_bm25", retriever=retriever)

    # Set up store
    store = SQLiteStore(db_path=".retobs/quickstart.db")
    await store.init_db()
    await store.save_run("run_qs", "quickstart", "{}")

    # Run benchmark
    runner = BenchmarkRunner(store=store, concurrency=4)
    results = await runner.run(pipelines=[pipeline], queries=queries, run_id="run_qs")
    print(f"Completed {sum(len(v) for v in results.values())} pipeline-query pairs")

    # Compute and print metrics
    engine = MetricsEngine(recall_at_k_values=[1, 5, 10])
    all_results = [r for rs in results.values() for r in rs]
    await engine.compute_and_store("run_qs", store, all_results, qrels)
    aggregated = await engine.aggregate("run_qs", store)

    print("\n=== Results ===")
    for key, vals in sorted(aggregated.items()):
        if "latency" not in key:
            print(f"  {key}: {vals['mean']:.4f} ± {vals['std']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
