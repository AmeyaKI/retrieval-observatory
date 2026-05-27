from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="retobs", help="Retrieval Observatory — RAG pipeline benchmarking.")
console = Console()


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to experiment YAML config."),
    skip_smoke_test: bool = typer.Option(False, "--skip-smoke-test", help="Skip ID consistency smoke test."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass result cache; re-run all queries."),
) -> None:
    """Run a benchmark experiment and store results."""
    asyncio.run(_run(config, skip_smoke_test, no_cache))


async def _run(config_path: Path, skip_smoke_test: bool, no_cache: bool = False) -> None:
    from retrieval_observatory.config.schema import ExperimentConfig
    from retrieval_observatory.config.validator import validate_id_consistency
    from retrieval_observatory.datasets.beir import BEIRDataset
    from retrieval_observatory.datasets.custom import CustomDataset
    from retrieval_observatory.datasets.validation import dataset_fingerprint, validate_experiment_config
    from retrieval_observatory.metrics.diagnostics import build_query_diagnostics
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.pipeline.factory import build_pipeline_from_config
    from retrieval_observatory.runner.manifest import build_run_manifest
    from retrieval_observatory.runner.benchmark import BenchmarkRunner
    from retrieval_observatory.runner.cache import ResultCache
    from retrieval_observatory.store.sqlite import SQLiteStore

    cfg = ExperimentConfig.from_yaml(str(config_path))
    _resolve_config_paths(cfg, config_path.parent)
    console.print(f"[bold green]Experiment:[/bold green] {cfg.experiment.name}")
    validation_report = validate_experiment_config(cfg, str(config_path))
    if validation_report["status"] == "error":
        _print_validation_report(validation_report)
        raise typer.Exit(1)

    # Load dataset
    console.print(f"[bold]Loading dataset:[/bold] {cfg.dataset.name}")
    if cfg.dataset.name.startswith("beir/") or cfg.dataset.name in _BEIR_NAMES:
        dataset = BEIRDataset(
            dataset_name=cfg.dataset.name,
            split=cfg.dataset.split,
            max_queries=cfg.dataset.max_queries,
        )
    elif cfg.dataset.name == "custom":
        if not cfg.dataset.queries_path:
            console.print("[red]Error: queries_path required for custom dataset[/red]")
            raise typer.Exit(1)
        dataset = CustomDataset(
            queries_path=cfg.dataset.queries_path,
            corpus_path=cfg.dataset.corpus_path,
            qrels_path=cfg.dataset.qrels_path,
            temporal_field=cfg.dataset.temporal_field,
            timestamp_field=cfg.dataset.timestamp_field,
            metadata_fields=cfg.dataset.metadata_fields,
        )
    else:
        console.print(f"[red]Unknown dataset: {cfg.dataset.name}[/red]")
        raise typer.Exit(1)

    queries, qrels = dataset.load()
    console.print(f"Loaded {len(queries)} queries, {len(qrels)} qrels")

    # Build pipelines — pass corpus for adapters that need it (e.g. adapter.bm25)
    corpus = dataset.corpus if hasattr(dataset, "corpus") else None
    pipelines = [build_pipeline_from_config(p.model_dump(), corpus=corpus) for p in cfg.pipelines]
    console.print(f"Built {len(pipelines)} pipeline(s): {[p.pipeline_id for p in pipelines]}")

    # Init store
    if cfg.output.store == "postgres":
        import os
        from retrieval_observatory.store.postgres import PostgresStore
        dsn = cfg.output.postgres_dsn or os.environ.get("RETOBS_POSTGRES_DSN")
        if not dsn:
            console.print("[red]Postgres store selected but no DSN found. Set postgres_dsn in config or RETOBS_POSTGRES_DSN env var.[/red]")
            raise typer.Exit(1)
        store = PostgresStore(dsn=dsn)
    else:
        store = SQLiteStore(db_path=cfg.output.db_path)
    await store.init_db()

    run_id = str(uuid.uuid4())[:8]
    await store.save_run(
        run_id=run_id,
        experiment_name=cfg.experiment.name,
        config_json=cfg.model_dump_json(),
    )
    if hasattr(store, "save_validation_report"):
        await store.save_validation_report(validation_report, config_path=str(config_path), run_id=run_id)
    if hasattr(store, "save_run_manifest"):
        fingerprint = dataset_fingerprint(
            cfg.dataset.name,
            queries,
            qrels,
            corpus if isinstance(corpus, dict) else None,
        )
        await store.save_run_manifest(run_id, build_run_manifest(cfg, fingerprint))
    console.print(f"[bold]Run ID:[/bold] {run_id}")

    # ID consistency smoke test
    if not skip_smoke_test and hasattr(dataset, "corpus"):
        console.print("[bold]Running ID consistency smoke test...[/bold]")
        for pipeline in pipelines:
            await validate_id_consistency(pipeline, queries, dataset.corpus)
        console.print("[green]Smoke test passed.[/green]")

    # Build caches
    caches = {}
    if cfg.execution.cache_results and not no_cache:
        for pipeline_cfg in cfg.pipelines:
            import yaml
            caches[pipeline_cfg.id] = ResultCache(
                store=store,
                # sort_keys=True ensures the same config always produces the same YAML string
                pipeline_config_yaml=yaml.dump(pipeline_cfg.model_dump(), sort_keys=True),
            )

    # Run benchmark
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

    # Compute metrics
    console.print("[bold]Computing metrics...[/bold]")
    engine = MetricsEngine(
        recall_at_k_values=cfg.metrics.recall_at_k,
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
    await store.finish_run(run_id)

    # Print summary table
    _print_metrics_table(aggregated, run_id)

    # Export if requested
    if "json" in cfg.output.export:
        out_path = f".retobs/{run_id}_metrics.json"
        with open(out_path, "w") as f:
            json.dump(aggregated, f, indent=2)
        console.print(f"Exported JSON → {out_path}")

    console.print(f"\n[bold green]Done.[/bold green] Run ID: {run_id}")
    console.print(f"Results stored in: {cfg.output.db_path}")


@app.command()
def compare(
    run_id_1: str = typer.Argument(..., help="First run ID"),
    run_id_2: str = typer.Argument(..., help="Second run ID"),
    db_path: str = typer.Option(".retobs/results.db", "--db", help="SQLite database path"),
) -> None:
    """Compare two benchmark runs with significance testing."""
    asyncio.run(_compare(run_id_1, run_id_2, db_path))


async def _compare(run_id_1: str, run_id_2: str, db_path: str) -> None:
    from retrieval_observatory.metrics.comparison import paired_scores_by_query
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.metrics.significance import paired_bootstrap_test
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)

    engine = MetricsEngine()
    agg1 = await engine.aggregate(run_id_1, store)
    agg2 = await engine.aggregate(run_id_2, store)

    # Build comparison table
    all_keys = sorted(set(agg1.keys()) | set(agg2.keys()))

    table = Table(title=f"Run Comparison: {run_id_1} vs {run_id_2}")
    table.add_column("Metric", style="bold")
    table.add_column(run_id_1, justify="right")
    table.add_column(run_id_2, justify="right")
    table.add_column("p-value", justify="right")

    metrics1 = await store.get_metrics(run_id_1)
    metrics2 = await store.get_metrics(run_id_2)

    for key in all_keys:
        a1 = agg1.get(key, {})
        a2 = agg2.get(key, {})
        mean1 = f"{a1.get('mean', 0):.4f} ± {a1.get('std', 0):.4f}" if a1 else "—"
        mean2 = f"{a2.get('mean', 0):.4f} ± {a2.get('std', 0):.4f}" if a2 else "—"

        p_val = "—"
        s1, s2, n_pairs = paired_scores_by_query(metrics1, metrics2, key)
        if s1 and s2:
            p = paired_bootstrap_test(s1, s2)
            p_val = f"{p:.3f}" + (" *" if p < 0.05 else "") + f" ({n_pairs} pairs)"

        table.add_row(key, mean1, mean2, p_val)

    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    db_path: str = typer.Option(".retobs/results.db", "--db"),
) -> None:
    """Start the FastAPI dashboard server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[/red]")
        raise typer.Exit(1)

    try:
        from retrieval_observatory.dashboard.api import create_app
        dashboard_app = create_app(db_path=db_path)
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        console.print(f"[bold green]Dashboard:[/bold green] http://{display_host}:{port}")
        uvicorn.run(dashboard_app, host=host, port=port)
    except ImportError:
        console.print("[red]Dashboard not available. Install fastapi: pip install fastapi uvicorn[/red]")
        raise typer.Exit(1)


_BEIR_NAMES = {
    "msmarco", "trec-covid", "nfcorpus", "nq", "hotpotqa", "fiqa",
    "arguana", "webis-touche2020", "cqadupstack", "quora", "dbpedia-entity",
    "scidocs", "fever", "climate-fever", "scifact", "signal1m", "trec-news", "robust04",
}


def _print_metrics_table(aggregated: dict, run_id: str) -> None:
    table = Table(title=f"Results — Run {run_id}")
    table.add_column("Metric", style="bold")
    table.add_column("Mean", justify="right")
    table.add_column("Std", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("N", justify="right")

    for key, vals in sorted(aggregated.items()):
        ci = f"[{vals['ci_low']:.4f}, {vals['ci_high']:.4f}]"
        table.add_row(
            key,
            f"{vals['mean']:.4f}",
            f"{vals['std']:.4f}",
            ci,
            str(vals["n"]),
        )

    console.print(table)


@app.command()
def validate(
    config: Path = typer.Option(..., "--config", "-c", help="Path to experiment YAML config."),
    db_path: str = typer.Option(".retobs/results.db", "--db", help="Optional SQLite DB for saving the report."),
) -> None:
    """Validate a benchmark config before running it."""
    from retrieval_observatory.config.schema import ExperimentConfig
    from retrieval_observatory.datasets.validation import validate_experiment_config
    from retrieval_observatory.store.sqlite import SQLiteStore

    cfg = ExperimentConfig.from_yaml(str(config))
    _resolve_config_paths(cfg, config.parent)
    report = validate_experiment_config(cfg, str(config))
    _print_validation_report(report)

    async def _save() -> None:
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        await store.save_validation_report(report, config_path=str(config))

    asyncio.run(_save())
    if report["status"] == "error":
        raise typer.Exit(1)


@app.command()
def init(
    output: Path = typer.Option(Path("retobs_experiment.yaml"), "--output", "-o"),
    mode: str = typer.Option("custom-jsonl", "--mode", help="beir, custom-jsonl, http-endpoint, bm25+dense, bm25+reranker"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    sample_dataset: bool = typer.Option(True, "--sample-dataset/--no-sample-dataset", help="Write tiny custom JSONL files."),
) -> None:
    """Generate a starter config and optional tiny custom dataset files."""
    import yaml

    if output.exists() and not force:
        console.print(f"[red]Refusing to overwrite {output}. Pass --force to replace it.[/red]")
        raise typer.Exit(1)

    config = _starter_config(mode)
    output.write_text(yaml.safe_dump(config, sort_keys=False))
    console.print(f"[green]Wrote config:[/green] {output}")

    if sample_dataset and mode in {"custom-jsonl", "http-endpoint", "bm25+dense", "bm25+reranker"}:
        data_dir = output.parent / "retobs_sample_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        queries_path = data_dir / "queries.jsonl"
        corpus_path = data_dir / "corpus.jsonl"
        if force or not queries_path.exists():
            queries_path.write_text(
                '{"query_id":"q1","text":"What is hybrid retrieval?","relevant_doc_ids":{"d1":2},"tags":["sample"]}\n'
            )
        if force or not corpus_path.exists():
            corpus_path.write_text(
                '{"id":"d1","title":"Hybrid retrieval","text":"Hybrid retrieval combines lexical and dense search.","timestamp":"2024-01-01T00:00:00","source":"sample"}\n'
                '{"id":"d2","title":"Reranking","text":"Rerankers rescore candidate documents for a query.","timestamp":"2024-01-02T00:00:00","source":"sample"}\n'
            )
        console.print(f"[green]Wrote sample dataset:[/green] {data_dir}")


def _print_validation_report(report: dict) -> None:
    table = Table(title=f"Validation — {report['status'].upper()}")
    table.add_column("Level", style="bold")
    table.add_column("Check")
    table.add_column("Message")
    style = {"ok": "green", "warning": "yellow", "error": "red"}
    for item in report["items"]:
        table.add_row(f"[{style.get(item['level'], 'white')}]{item['level']}[/]", item["check"], item["message"])
    console.print(table)


def _starter_config(mode: str) -> dict:
    dataset = {
        "type": "custom",
        "name": "custom",
        "queries_path": "retobs_sample_data/queries.jsonl",
        "corpus_path": "retobs_sample_data/corpus.jsonl",
        "timestamp_field": "timestamp",
        "metadata_fields": ["source"],
    }
    stages = {
        "bm25": {"type": "adapter.bm25", "config": {"k": 100}},
        "dense": {"type": "adapter.hf_biencoder", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2", "k": 100}},
        "rerank": {"type": "adapter.hf_crossencoder", "config": {"model": "cross-encoder/ms-marco-MiniLM-L-6-v2", "k": 10}},
    }
    if mode == "beir":
        dataset = {"type": "beir", "name": "beir/nfcorpus", "split": "test", "max_queries": 50}
    if mode == "http-endpoint":
        return {
            "experiment": {"name": "http-endpoint-eval"},
            "dataset": dataset,
            "pipelines": [{"id": "http_retriever", "stages": [{"type": "adapter.http", "url": "http://localhost:8000/search", "config": {"k": 10}}]}],
            "metrics": {"recall_at_k": [1, 5, 10], "ndcg_at_k": [10], "mrr": True, "map": True},
            "execution": {"concurrency": 4, "timeout_seconds": 30},
            "output": {"store": "sqlite", "db_path": ".retobs/results.db"},
        }
    include = [["bm25"]]
    if mode in {"bm25+dense", "beir"}:
        include = [["bm25"], ["dense"]]
    if mode == "bm25+reranker":
        include = [["bm25"], ["bm25", "rerank"]]
    return {
        "experiment": {"name": f"{mode}-eval"},
        "dataset": dataset,
        "stages": stages,
        "combinations": {"include": include},
        "metrics": {"recall_at_k": [1, 5, 10, 20], "ndcg_at_k": [10], "mrr": True, "map": True},
        "execution": {"concurrency": 4, "timeout_seconds": 60, "cache_results": True},
        "output": {"store": "sqlite", "db_path": ".retobs/results.db", "export": ["json"]},
    }


def _resolve_config_paths(cfg, base_dir: Path) -> None:
    ds = cfg.dataset
    for attr in ("queries_path", "corpus_path", "qrels_path"):
        value = getattr(ds, attr, None)
        if value and not Path(value).is_absolute():
            setattr(ds, attr, str(base_dir / value))


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


if __name__ == "__main__":
    app()
