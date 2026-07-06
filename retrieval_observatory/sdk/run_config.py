from __future__ import annotations

from typing import Any, Dict, Optional, Union

from retrieval_observatory.sdk.report import BenchmarkReport, _run_sync

# Config-first entry point. Takes an ``ExperimentConfig``-shaped dict/JSON (adapter specs, not
# live Python objects) and routes it through the same shared executor as ``retobs run`` and
# ``retrieval_observatory.benchmark``. This is the single reusable seam the REST layer and MCP
# server both call: pipelines expressed as configuration, runnable over the wire.

_BEIR_PREFIX = "beir/"


def run_from_config(
    config: Union[Dict[str, Any], Any],
    *,
    db_path: Optional[str] = None,
    max_queries: Optional[int] = None,
    run_id: Optional[str] = None,
    no_cache: bool = False,
) -> BenchmarkReport:
    """Run a benchmark from an ``ExperimentConfig``-shaped dict (or an ExperimentConfig).

    ``config`` is JSON/dict of the same shape as a ``retobs run`` YAML file — an experiment
    with a dataset and one or more pipelines built from adapter specs (``adapter.bm25``,
    ``adapter.http``, ``adapter.rrf``, dense, ...). ``max_queries`` caps the query count for
    bounded/quick runs (used by the MCP tools and the REST ``wait=true`` mode); when set it also
    overrides ``dataset.max_queries``. ``db_path`` overrides the config's output db path.

    Returns a :class:`BenchmarkReport`, identical to what ``benchmark()`` returns.
    """
    return _run_sync(
        _run_from_config_async(
            config=config,
            db_path=db_path,
            max_queries=max_queries,
            run_id=run_id,
            no_cache=no_cache,
        )
    )


async def _run_from_config_async(
    *,
    config,
    db_path,
    max_queries,
    run_id,
    no_cache,
) -> BenchmarkReport:
    from retrieval_observatory.config.schema import ExperimentConfig
    from retrieval_observatory.pipeline.factory import build_pipeline_from_config
    from retrieval_observatory.runner.execute import execute_benchmark
    from retrieval_observatory.store.postgres import PostgresStore
    from retrieval_observatory.store.sqlite import SQLiteStore

    cfg = config if isinstance(config, ExperimentConfig) else ExperimentConfig.model_validate(config)

    if max_queries is not None:
        cfg.dataset.max_queries = max_queries
    if db_path is not None:
        cfg.output.db_path = db_path

    dataset = _build_dataset(cfg)
    queries, qrels = dataset.load()
    if max_queries is not None:
        queries = queries[:max_queries]
        ids = {q.query_id for q in queries}
        qrels = {qid: rel for qid, rel in qrels.items() if qid in ids}
    corpus = dataset.corpus if hasattr(dataset, "corpus") else None

    if cfg.output.store == "postgres":
        import os

        dsn = cfg.output.postgres_dsn or os.environ.get("RETOBS_POSTGRES_DSN")
        if not dsn:
            raise ValueError(
                "Postgres store selected but no DSN found. Set output.postgres_dsn in the "
                "config or the RETOBS_POSTGRES_DSN env var."
            )
        store = PostgresStore(dsn=dsn)
        effective_db_path = dsn
    else:
        store = SQLiteStore(db_path=cfg.output.db_path)
        effective_db_path = cfg.output.db_path
    await store.init_db()

    from retrieval_observatory.pipeline.factory import build_dag_from_config
    pipelines = [build_pipeline_from_config(p.model_dump(), corpus=corpus) for p in cfg.pipelines]
    pipelines += [build_dag_from_config(g.model_dump(), corpus=corpus) for g in cfg.graphs]
    if not pipelines:
        raise ValueError("Config defines no pipelines; add at least one entry under 'pipelines' or 'graphs'.")

    artifacts = await execute_benchmark(
        cfg=cfg,
        dataset=dataset,
        queries=queries,
        qrels=qrels,
        corpus=corpus,
        pipelines=pipelines,
        store=store,
        run_id=run_id,
        no_cache=no_cache,
    )
    return BenchmarkReport(artifacts, db_path=effective_db_path, experiment_name=cfg.experiment.name)


def _build_dataset(cfg):
    """Construct a dataset object from an ExperimentConfig (BEIR or custom JSONL)."""
    from retrieval_observatory.datasets.beir import BEIRDataset
    from retrieval_observatory.datasets.custom import CustomDataset

    name = cfg.dataset.name
    if name.startswith(_BEIR_PREFIX):
        return BEIRDataset(
            dataset_name=name,
            split=cfg.dataset.split,
            max_queries=cfg.dataset.max_queries,
        )
    if cfg.dataset.type == "custom" or name == "custom" or cfg.dataset.queries_path:
        if not cfg.dataset.queries_path:
            raise ValueError("queries_path required for a custom dataset (dataset.queries_path).")
        return CustomDataset(
            queries_path=cfg.dataset.queries_path,
            corpus_path=cfg.dataset.corpus_path,
            qrels_path=cfg.dataset.qrels_path,
            temporal_field=cfg.dataset.temporal_field,
            timestamp_field=cfg.dataset.timestamp_field,
            metadata_fields=cfg.dataset.metadata_fields,
        )
    raise ValueError(
        f"Unknown dataset '{name}'. Use a 'beir/<name>' id, or set dataset.type='custom' with "
        "queries_path/corpus_path/qrels_path."
    )
