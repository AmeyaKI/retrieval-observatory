#!/usr/bin/env python3
"""Execute the demo pipeline over the HotpotQA sample and persist a retobs Run.

This goes through `execute_benchmark`, the shared executor that both `retobs evaluate` and
the Python SDK route through, rather than `retobs.evaluate()` directly. Two reasons, both
verified rather than assumed:

  * `evaluate()` builds its own run configuration internally and has no way to declare a
    release identity — the corpus / index / chunking / embedding / reranker revisions that
    retobs compares runs on. The comparability scenario depends on those.
  * `evaluate()` accepts linear stages plus one fused first stage. It cannot express a graph
    with routing gates, and neither can the YAML pipeline builder.

Everything downstream — `compare()`, `inspect_query()`, the reports, the dashboard — is the
ordinary retobs surface reading an ordinary retobs Run.

Usage:
    python run.py --name baseline --max-queries 20
    python run.py --name baseline
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import time
from pathlib import Path

from retrieval_observatory.datasets.custom import CustomDataset
from retrieval_observatory.runner.execute import execute_benchmark
from retrieval_observatory.store.sqlite import SQLiteStore

from pipeline import DemoCorpus, PipelineSettings, build_config, build_pipeline

HERE = Path(__file__).parent
DEFAULT_DATA_DIR = HERE / "data"
DEFAULT_DB = str(HERE / ".retobs" / "demo.db")


def load_dataset(data_dir: Path, final_k: int):
    dataset = CustomDataset(
        queries_path=str(data_dir / "queries.jsonl"),
        corpus_path=str(data_dir / "corpus.jsonl"),
        qrels_path=str(data_dir / "qrels.jsonl"),
        k=final_k,
    )
    queries, qrels = dataset.load()
    return dataset, queries, qrels


async def run(
    *,
    name: str,
    settings: PipelineSettings,
    data_dir: Path,
    db_path: str,
    max_queries: int | None,
    embedding_model_revision: str | None = None,
    index_build_id_override: str | None = None,
    log=print,
):
    corpus = DemoCorpus.load(data_dir)
    dataset, queries, qrels = load_dataset(data_dir, settings.final_k)
    if max_queries is not None:
        queries = queries[:max_queries]
        kept = {query.query_id for query in queries}
        qrels = {qid: rel for qid, rel in qrels.items() if qid in kept}

    log(f"corpus {len(corpus.index_text):,} docs | queries {len(queries):,} | run '{name}'")

    config = build_config(
        corpus,
        settings,
        experiment_name=name,
        embedding_model_revision=embedding_model_revision,
        index_build_id_override=index_build_id_override,
    )
    pipeline = build_pipeline(corpus, settings)

    # Warm the indexes and models on one throwaway query, serially, before the run starts.
    # Both search lanes build their index lazily on first use; without this, every query in
    # the first concurrent wave triggers its own build of the same index, and each of those
    # blows the per-query timeout. Cost is paid once; the vector index is then cached to disk.
    warm_started = time.perf_counter()
    await pipeline.run(dataclasses.replace(queries[0], query_id="__warmup__"))
    log(f"warmed indexes and models in {time.perf_counter() - warm_started:.1f}s")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    artifacts = await execute_benchmark(
        cfg=config,
        dataset=dataset,
        queries=queries,
        qrels=qrels,
        corpus=corpus.index_text,
        pipelines=[pipeline],
        store=store,
        no_cache=True,
        # The difficulty classifier is deliberately unused: both routing decisions in this
        # pipeline are deterministic, so nothing needs a predicted label.
        annotate_difficulty=False,
        log=lambda *a, **k: None,
    )
    return artifacts, queries, qrels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="baseline")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--no-bm25", action="store_true", help="disable the keyword lane (regression variant)")
    args = parser.parse_args()

    settings = PipelineSettings(bm25_lane_enabled=not args.no_bm25)
    artifacts, queries, _ = asyncio.run(
        run(
            name=args.name,
            settings=settings,
            data_dir=args.data_dir,
            db_path=args.db,
            max_queries=args.max_queries,
        )
    )
    print(f"\nrun_id: {artifacts.run_id}")
    if artifacts.error_samples:
        print(f"errors: {artifacts.error_samples[:3]}")
    print(json.dumps(artifacts.aggregated, indent=2, default=str)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
