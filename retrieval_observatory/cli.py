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
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.pipeline.factory import build_pipeline_from_config
    from retrieval_observatory.runner.benchmark import BenchmarkRunner
    from retrieval_observatory.runner.cache import ResultCache
    from retrieval_observatory.store.sqlite import SQLiteStore

    cfg = ExperimentConfig.from_yaml(str(config_path))
    console.print(f"[bold green]Experiment:[/bold green] {cfg.experiment.name}")

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
    await engine.compute_and_store(
        run_id=run_id,
        store=store,
        results=all_results,
        qrels=qrels,
        queries_by_id=queries_by_id,
    )

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

    from collections import defaultdict
    scores1: dict = defaultdict(list)
    scores2: dict = defaultdict(list)
    for row in metrics1:
        key = f"{row['pipeline_id']}|stage{row['stage_index']}|{row['metric_name']}@{row['k']}"
        scores1[key].append(row["value"])
    for row in metrics2:
        key = f"{row['pipeline_id']}|stage{row['stage_index']}|{row['metric_name']}@{row['k']}"
        scores2[key].append(row["value"])

    for key in all_keys:
        a1 = agg1.get(key, {})
        a2 = agg2.get(key, {})
        mean1 = f"{a1.get('mean', 0):.4f} ± {a1.get('std', 0):.4f}" if a1 else "—"
        mean2 = f"{a2.get('mean', 0):.4f} ± {a2.get('std', 0):.4f}" if a2 else "—"

        p_val = "—"
        s1 = scores1.get(key, [])
        s2 = scores2.get(key, [])
        if s1 and s2 and len(s1) == len(s2):
            p = paired_bootstrap_test(s1, s2)
            p_val = f"{p:.3f}" + (" *" if p < 0.05 else "")

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


if __name__ == "__main__":
    app()
