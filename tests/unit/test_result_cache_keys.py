"""Result caches must not serve a stale hit after the corpus changes, after a dataset switch that
reuses query ids, or for a different query text under the same id."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from retrieval_observatory.config.schema import ExperimentConfig, PipelineConfig
from retrieval_observatory.datasets.inmemory import InMemoryDataset
from retrieval_observatory.datasets.validation import dataset_fingerprint
from retrieval_observatory.pipeline.factory import build_pipeline_from_config
from retrieval_observatory.runner.benchmark import BenchmarkRunner
from retrieval_observatory.runner.cache import ResultCache, StageResultCache
from retrieval_observatory.runner.execute import execute_benchmark
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Query

CORPUS_V1 = {"d1": "apple pie recipe", "d2": "banana bread", "d3": "cherry tart"}
CORPUS_V2 = {"d1": "quantum physics", "d2": "banana bread", "d3": "cherry tart", "d4": "apple pie recipe rewritten"}
PIPELINE = {"id": "p", "stages": [{"type": "adapter.bm25", "config": {"k": 3}}]}


def _fingerprint(corpus: dict, queries: list[Query]) -> dict:
    return dataset_fingerprint("custom", queries, {}, corpus)


def test_result_cache_key_includes_dataset_and_query_text():
    store = MagicMock()
    config_yaml = yaml.dump(PIPELINE, sort_keys=True)
    q1 = [Query("apple pie", k=3, query_id="q1")]
    a = ResultCache(store, config_yaml, _fingerprint(CORPUS_V1, q1))
    b = ResultCache(store, config_yaml, _fingerprint(CORPUS_V2, q1))

    assert a._key("q1", "apple pie") == ResultCache(store, config_yaml, _fingerprint(CORPUS_V1, q1))._key("q1", "apple pie")
    assert a._key("q1", "apple pie") != b._key("q1", "apple pie")
    assert a._key("q1", "apple pie") != a._key("q1", "quantum physics")
    # Adding queries or relabelling does not invalidate entries for unchanged queries.
    more = q1 + [Query("banana", k=3, query_id="q2")]
    assert a._key("q1", "apple pie") == ResultCache(store, config_yaml, _fingerprint(CORPUS_V1, more))._key("q1", "apple pie")


def test_stage_cache_key_includes_dataset_and_query_text():
    stage_cfg = PipelineConfig.model_validate(PIPELINE).stages[0].model_dump()
    q1 = [Query("apple pie", k=3, query_id="q1")]
    cache = StageResultCache(MagicMock())
    unbound = cache.key_for(stage_cfg, "q1", query_text="apple pie")
    cache.bind_dataset(_fingerprint(CORPUS_V1, q1))
    v1 = cache.key_for(stage_cfg, "q1", query_text="apple pie")
    cache.bind_dataset(_fingerprint(CORPUS_V2, q1))
    v2 = cache.key_for(stage_cfg, "q1", query_text="apple pie")

    assert len({unbound, v1, v2}) == 3
    assert v2 != cache.key_for(stage_cfg, "q1", query_text="quantum physics")


@pytest.mark.asyncio
async def test_runner_cache_misses_after_corpus_edit(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "x.db"))
    await store.init_db()
    for run_id in ("run1", "run2"):
        await store.save_run(run_id, "t", "{}")
    config_yaml = yaml.dump(PIPELINE, sort_keys=True)

    q_v1 = [Query("apple pie", k=3, query_id="q1")]
    p1 = build_pipeline_from_config(PIPELINE, corpus=CORPUS_V1)
    cache1 = {"p": ResultCache(store, config_yaml, _fingerprint(CORPUS_V1, q_v1))}
    r1 = await BenchmarkRunner(store=store, caches=cache1).run([p1], q_v1, "run1")
    assert r1["p"][0].snapshots[0].documents[0].id == "d1"

    # Same pipeline config, same query id; corpus edited (d1 rewritten) and the query text changed.
    q_v2 = [Query("quantum physics", k=3, query_id="q1")]
    p2 = build_pipeline_from_config(PIPELINE, corpus=CORPUS_V2)
    cache2 = {"p": ResultCache(store, config_yaml, _fingerprint(CORPUS_V2, q_v2))}
    r2 = await BenchmarkRunner(store=store, caches=cache2).run([p2], q_v2, "run2")
    fresh = await p2.run(q_v2[0])

    assert [d.id for d in r2["p"][0].snapshots[0].documents] == [d.id for d in fresh.snapshots[0].documents]
    assert r2["p"][0].snapshots[0].documents[0].text == "quantum physics"


@pytest.mark.asyncio
async def test_execute_benchmark_threads_dataset_identity_into_caches(tmp_path):
    """Two runs on one store with cache_results on: an edited corpus must not be served from cache."""
    cfg = ExperimentConfig.model_validate({
        "experiment": {"name": "cache"},
        "dataset": {"name": "custom", "queries_path": "unused"},
        "pipelines": [PIPELINE],
        "metrics": {"recall_at_k": [3]},
        "execution": {"cache_results": True},
    })
    store = SQLiteStore(db_path=str(tmp_path / "x.db"))
    await store.init_db()

    async def run(corpus: dict, text: str, relevant: str):
        dataset = InMemoryDataset(
            queries=[{"query_id": "q1", "text": text, "relevant_doc_ids": [relevant]}], corpus=corpus, k=3,
        )
        queries, qrels = dataset.load()
        pipeline = build_pipeline_from_config(PIPELINE, corpus=dataset.corpus, stage_cache=StageResultCache(store))
        art = await execute_benchmark(
            cfg=cfg, dataset=dataset, queries=queries, qrels=qrels, corpus=dataset.corpus, pipelines=[pipeline], store=store,
        )
        return (await store.get_traces(art.run_id))[0]

    first = await run(CORPUS_V1, "apple pie", "d1")
    second = await run(CORPUS_V2, "quantum physics", "d1")

    assert first.spans[-1].outputs[0].doc_id == "d1"
    assert second.spans[-1].outputs[0].doc_id == "d1"
    assert [c.doc_id for c in second.spans[-1].outputs] == ["d1"]  # only d1 mentions quantum physics in v2
