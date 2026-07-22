from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from retrieval_observatory.types import PipelineResult, Query

# Shared benchmark execution core used by BOTH the CLI (`retobs run`) and the Python SDK
# (`retrieval_observatory.benchmark`). Keeping a single executor guarantees that both paths
# produce identical artifacts and write the same query lineage (save_run_queries + manifest),
# which the Test Sets -> Benchmark -> Production -> Findings join depends on.


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
    from retrieval_observatory.diagnostics.engine import DiagnosticEngine, context_for_trace
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.runner.benchmark import BenchmarkRunner
    from retrieval_observatory.runner.cache import ResultCache
    from retrieval_observatory.runner.manifest import build_run_manifest, detect_forge_dataset_id

    _log = log or (lambda *a, **k: None)
    run_started_at = datetime.now(timezone.utc)

    # Detect filter-ignorance early so the warning appears before any queries run.
    filter_warnings: list[str] = []
    queries_with_filters = [q for q in queries if q.filters]
    if queries_with_filters:
        for pipeline in pipelines:
            retriever = getattr(pipeline, "retriever", None) or getattr(pipeline, "_retriever", None)
            if retriever is not None and not getattr(retriever, "supports_filters", True):
                filter_warnings.append(
                    f"Pipeline '{pipeline.pipeline_id}': {len(queries_with_filters)} "
                    f"quer{'y' if len(queries_with_filters) == 1 else 'ies'} have filters but "
                    f"adapter '{retriever.retriever_id}' does not support Query.filters — "
                    "results are unfiltered and metrics will be inflated."
                )
                _log(f"[yellow]Warning:[/yellow] {filter_warnings[-1]}")

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
        manifest = build_run_manifest(
            cfg,
            fingerprint,
            latency_budget_ms=latency_budget_ms,
            forge_dataset_id=forge_dataset_id,
            golden_set=golden_set,
            seed=getattr(cfg.execution, "seed", None),
        )
        effective_cache = bool(cfg.execution.cache_results and not no_cache)
        manifest["cache_results"] = effective_cache
        manifest["execution"]["cache_results"] = effective_cache
        if filter_warnings:
            manifest["run_warnings"] = filter_warnings
        await store.save_run_manifest(run_id, manifest)
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
        seed=getattr(cfg.execution, "seed", None),
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
    if hasattr(store, "save_qrels"):
        # Persist the qrels actually used for scoring so dashboard endpoints (operator
        # attribution, miss attribution) can recover ground truth after the run completes —
        # qrels only ever existed in-memory here otherwise.
        await store.save_qrels(run_id, qrels)
    traces = [result.trace for result in all_results if result.trace is not None]
    if len(traces) != len(all_results):
        raise RuntimeError("every evaluation result must carry a persisted execution trace")
    await engine.compute_from_traces(
        run_id=run_id,
        store=store,
        traces=[trace for trace in traces if trace.status == "OK"],
        qrels=qrels,
        queries_by_id=queries_by_id,
    )

    # Warn about unjudged queries: queries with no or empty qrel entries are excluded from
    # quality metric means (they contribute no metric_score row), so the dashboard n count
    # may be lower than the total query count.
    unjudged = [q.query_id for q in queries if not qrels.get(q.query_id)]
    if unjudged:
        n_unjudged = len(unjudged)
        msg = (
            f"{n_unjudged} quer{'y' if n_unjudged == 1 else 'ies'} have no relevance judgments "
            f"and are excluded from quality metric means. "
            f"Metrics reflect {len(queries) - n_unjudged} of {len(queries)} queries."
        )
        _log(f"[yellow]Warning:[/yellow] {msg}")
        if hasattr(store, "save_run_manifest"):
            # Append to existing run_warnings in the manifest (may already have filter_warnings)
            existing = await store.get_run_manifest(run_id) or {}
            existing_warnings = existing.get("run_warnings", [])
            if msg not in existing_warnings:
                existing_warnings.append(msg)
                existing["run_warnings"] = existing_warnings
                existing["unjudged_query_count"] = n_unjudged
                await store.save_run_manifest(run_id, existing)

    corpus_documents = getattr(dataset, "corpus_documents", None)
    corpus_doc_ids = set(corpus_documents) if corpus_documents is not None else None
    configured_cutoffs = list(getattr(cfg.metrics, "recall_at_k", []) or [10])
    diagnostic_cutoff = max(configured_cutoffs)
    diagnostics = []
    diagnostic_engine = DiagnosticEngine.default()
    for trace in traces:
        relevant_ids = {doc_id for doc_id, grade in qrels.get(trace.query_id, {}).items() if grade > 0}
        context = context_for_trace(
            trace,
            relevant_document_ids=relevant_ids,
            corpus_document_ids=corpus_doc_ids,
            cutoff=diagnostic_cutoff,
        )
        findings = diagnostic_engine.evaluate(context)
        await store.save_diagnostics(run_id, trace.query_id, findings)
        diagnostics.append({
            "run_id": run_id,
            "query_id": trace.query_id,
            "pipeline_id": trace.pipeline_id,
            "difficulty_bucket": "unknown",
            "failure_labels": [finding.label for finding in findings if finding.availability.value == "supported"],
            "missing_relevant_ids": [],
            "stage_hits": {},
            "diagnostic_evidence": [finding.to_dict() for finding in findings],
        })
    aggregated = await engine.aggregate(run_id=run_id, store=store)
    metrics_rows = await store.get_metrics(run_id)
    if hasattr(store, "save_run_manifest"):
        manifest = await store.get_run_manifest(run_id) or {}
        completed_query_ids = {result.query_id for result in all_results if result.status == "OK"}
        labeled_query_ids = {query.query_id for query in queries if qrels.get(query.query_id)}
        cache_hits = sum(
            bool(span.params.get("cache_hit"))
            for trace in traces
            for span in trace.spans
        )
        observed = manifest.setdefault("execution", {}).setdefault("observed", {})
        observed.update({
            "cache_hits": cache_hits,
            "cache_misses": None,
            "timeouts": sum(result.status == "TIMEOUT" for result in all_results),
            "retries": None,
        })
        manifest["counts"] = {
            "attempted": len(queries),
            "completed": len(completed_query_ids),
            "labeled": len(labeled_query_ids),
            "metric_eligible": len(completed_query_ids & labeled_query_ids),
        }
        manifest["duration_semantics"] = {
            "total_latency_ms": "query wall clock",
            "critical_path_ms": "longest observed dependency path",
            "operator_sum_ms": "sum of observed operator durations",
        }
        run_finished_at = datetime.now(timezone.utc)
        manifest["run_window"] = {
            "started_at": run_started_at.isoformat(),
            "finished_at": run_finished_at.isoformat(),
        }
        from retrieval_observatory.release.evidence import EvidenceProfile

        health = None
        service_id = (manifest.get("release_identity") or {}).get("service_id")
        if service_id and hasattr(store, "get_instrumentation_health"):
            health = await store.get_instrumentation_health(service_id)
        manifest["evidence_profile"] = EvidenceProfile.from_run(manifest, traces, health).model_dump(mode="json")
        await store.save_run_manifest(run_id, manifest)
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
