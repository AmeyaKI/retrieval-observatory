from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from retrieval_observatory.types import PipelineResult, Query

# Shared benchmark execution core used by BOTH the CLI (`retobs run`) and the Python SDK
# (`retrieval_observatory.benchmark`). Keeping a single executor guarantees that both paths
# produce identical artifacts and write the same query lineage (save_run_queries + manifest),
# which the Forge -> Benchmark -> TraceLens -> Advisor join depends on.


@dataclass
class BenchmarkArtifacts:
    run_id: str
    aggregated: Dict[str, Any]
    metrics_rows: List[Dict[str, Any]]
    diagnostics: list
    error_samples: List[str]
    pipeline_ids: List[str]
    results_by_pipeline: Dict[str, List[PipelineResult]] = field(default_factory=dict)


async def execute_benchmark(
    *,
    cfg,
    dataset,
    queries: List[Query],
    qrels: Dict[str, Dict[str, int]],
    corpus: Optional[dict],
    pipelines: list,
    store,
    run_id: Optional[str] = None,
    no_cache: bool = False,
    latency_budget_ms: Optional[int] = None,
    golden_set: Optional[str] = None,
    validation_report: Optional[dict] = None,
    config_path: Optional[str] = None,
    annotate_difficulty: bool = True,
    log: Optional[Callable[..., None]] = None,
) -> BenchmarkArtifacts:
    """Run all pipelines over all queries, persist results + lineage, compute and store metrics.

    `store` must already be initialised (`await store.init_db()`). `pipelines` are pre-built
    pipeline objects. `log` is an optional status-printing callable (the CLI passes
    `console.print`; the SDK leaves it None for silent operation).
    """
    from retrieval_observatory.datasets.validation import dataset_fingerprint
    from retrieval_observatory.metrics.diagnostics import build_query_diagnostics
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.runner.benchmark import BenchmarkRunner
    from retrieval_observatory.runner.cache import ResultCache
    from retrieval_observatory.runner.manifest import build_run_manifest, detect_forge_dataset_id

    _log = log or (lambda *a, **k: None)

    run_id = run_id or str(uuid.uuid4())[:8]
    await store.save_run(
        run_id=run_id,
        experiment_name=cfg.experiment.name,
        config_json=cfg.model_dump_json(),
    )
    if validation_report is not None and hasattr(store, "save_validation_report"):
        await store.save_validation_report(validation_report, config_path=config_path, run_id=run_id)
    if hasattr(store, "save_run_manifest"):
        fingerprint = dataset_fingerprint(
            cfg.dataset.name,
            queries,
            qrels,
            corpus if isinstance(corpus, dict) else None,
        )
        forge_dataset_id = detect_forge_dataset_id(cfg)
        await store.save_run_manifest(
            run_id,
            build_run_manifest(
                cfg,
                fingerprint,
                latency_budget_ms=latency_budget_ms,
                forge_dataset_id=forge_dataset_id,
                golden_set=golden_set,
            ),
        )
    if hasattr(store, "save_run_queries"):
        await store.save_run_queries(run_id, queries, cfg.dataset.name)
    _log(f"[bold]Run ID:[/bold] {run_id}")

    if annotate_difficulty:
        _annotate_query_difficulty(queries, cfg.dataset.name, log=_log)

    # Build per-pipeline result caches. (Cross-pipeline StageResultCache, if any, is wired into
    # the pipeline objects by the caller at build time.)
    caches: Dict[str, ResultCache] = {}
    if cfg.execution.cache_results and not no_cache:
        import yaml

        for pipeline_cfg in cfg.pipelines:
            caches[pipeline_cfg.id] = ResultCache(
                store=store,
                pipeline_config_yaml=yaml.dump(pipeline_cfg.model_dump(), sort_keys=True),
            )

    runner = BenchmarkRunner(
        store=store,
        concurrency=cfg.execution.concurrency,
        timeout_ms=cfg.execution.timeout_ms,
        retry_attempts=cfg.execution.retry_attempts,
        caches=caches,
    )
    results_by_pipeline = await runner.run(
        pipelines=pipelines,
        queries=queries,
        run_id=run_id,
    )

    _log("[bold]Computing metrics...[/bold]")
    engine = MetricsEngine(
        recall_at_k_values=cfg.metrics.recall_at_k,
        precision_at_k_values=cfg.metrics.precision_at_k,
        ndcg_at_k_values=cfg.metrics.ndcg_at_k,
        temporal_recall_at_k_values=cfg.metrics.temporal_recall_at_k,
        latency_percentile_values=cfg.metrics.latency_percentiles,
        compute_mrr=cfg.metrics.mrr,
        compute_map=cfg.metrics.map,
    )
    all_results = [r for rs in results_by_pipeline.values() for r in rs]
    queries_by_id = {q.query_id: q for q in queries}
    if cfg.labels.mode != "gold":
        judged_qrels = await _build_llm_judged_qrels(cfg, queries, all_results, queries_by_id)
        if cfg.labels.mode == "pooled_llm_judge":
            qrels = _merge_qrels(qrels, judged_qrels)
        else:
            qrels = judged_qrels
    await engine.compute_and_store(
        run_id=run_id,
        store=store,
        results=all_results,
        qrels=qrels,
        queries_by_id=queries_by_id,
        corpus_documents=getattr(dataset, "corpus_documents", None),
    )
    diagnostics = build_query_diagnostics(run_id, all_results, qrels)
    if hasattr(store, "save_query_diagnostics"):
        await store.save_query_diagnostics(diagnostics)

    aggregated = await engine.aggregate(run_id=run_id, store=store)
    metrics_rows = await store.get_metrics(run_id)
    await store.finish_run(run_id)

    return BenchmarkArtifacts(
        run_id=run_id,
        aggregated=aggregated,
        metrics_rows=metrics_rows,
        diagnostics=diagnostics,
        error_samples=runner.error_samples,
        pipeline_ids=[p.pipeline_id for p in pipelines],
        results_by_pipeline=results_by_pipeline,
    )


async def _build_llm_judged_qrels(cfg, queries, all_results, queries_by_id):
    from retrieval_observatory.datasets.llm_judge import (
        AnthropicJudge,
        GeminiJudge,
        LLMJudgeDataset,
        OpenAIJudge,
    )

    judge_name = (cfg.labels.judge or "gemini").lower()
    if judge_name == "openai":
        judge = OpenAIJudge(model=cfg.labels.model or "gpt-4o-mini")
    elif judge_name == "anthropic":
        judge = AnthropicJudge(model=cfg.labels.model or "claude-haiku-4-5-20251001")
    else:
        judge = GeminiJudge(model=cfg.labels.model or "gemini-2.0-flash")
    dataset = LLMJudgeDataset(queries=queries, judge=judge, cache_path=cfg.labels.cache_path)
    return await dataset.judge_results(all_results, queries_by_id=queries_by_id)


def _merge_qrels(gold_qrels, judged_qrels):
    merged = {
        qid: rel.copy() if isinstance(rel, dict) else {doc_id: 1 for doc_id in rel}
        for qid, rel in gold_qrels.items()
    }
    for qid, rel in judged_qrels.items():
        target = merged.setdefault(qid, {})
        if isinstance(rel, dict):
            target.update(rel)
        else:
            for doc_id in rel:
                target[doc_id] = max(int(target.get(doc_id, 0)), 1)
    return merged


def _annotate_query_difficulty(queries, dataset_name: str, log: Optional[Callable[..., None]] = None) -> None:
    """Attach pre-retrieval difficulty predictions to query metadata when a model exists."""
    import os

    from retrieval_observatory.classifier.labels import default_model_path, normalize_dataset_name

    log = log or (lambda *a, **k: None)

    model_path = os.environ.get("RETOBS_CLASSIFIER_MODEL") or default_model_path(dataset_name)
    if not Path(model_path).exists():
        return
    try:
        from retrieval_observatory.classifier.model import load_model
    except ImportError:
        log("[yellow]Classifier model found but [classifier] extra not installed; skipping predictions.[/yellow]")
        return

    model = load_model(model_path)
    trained_on = model.metadata.get("dataset_name", "")
    if normalize_dataset_name(dataset_name) != normalize_dataset_name(trained_on):
        log(
            f"[yellow]Warning: classifier trained on '{trained_on}' but run uses '{dataset_name}'. "
            "Predictions may not be meaningful.[/yellow]"
        )

    for query in queries:
        pred = model.predict(query.text)
        query.metadata["predicted_difficulty"] = pred["label"]
        query.metadata["predicted_difficulty_proba"] = pred["proba"]
        query.metadata["predicted_difficulty_features"] = pred["features"]
    log(f"[dim]Applied difficulty predictions from {model_path}[/dim]")
