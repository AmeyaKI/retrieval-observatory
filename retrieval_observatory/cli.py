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
    latency_budget_ms: Optional[int] = typer.Option(None, "--latency-budget-ms", help="Latency budget per query in ms. If set, prints a verdict against stage deltas."),
) -> None:
    """Run a benchmark experiment and store results."""
    asyncio.run(_run(config, skip_smoke_test, no_cache, latency_budget_ms))


async def _run(config_path: Path, skip_smoke_test: bool, no_cache: bool = False, latency_budget_ms: Optional[int] = None) -> None:
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
    from retrieval_observatory.runner.cache import ResultCache, StageResultCache
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

    # Init store
    if cfg.output.store == "postgres":
        console.print("[yellow]Warning: PostgreSQL backend is community-supported and not CI-tested. SQLite is recommended for evaluation workloads.[/yellow]")
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

    # Build caches
    caches = {}
    stage_cache = None
    if cfg.execution.cache_results and not no_cache:
        import yaml
        stage_cache = StageResultCache(store=store)
        for pipeline_cfg in cfg.pipelines:
            caches[pipeline_cfg.id] = ResultCache(
                store=store,
                # sort_keys=True ensures the same config always produces the same YAML string
                pipeline_config_yaml=yaml.dump(pipeline_cfg.model_dump(), sort_keys=True),
            )

    pipelines = [build_pipeline_from_config(p.model_dump(), corpus=corpus, stage_cache=stage_cache) for p in cfg.pipelines]
    console.print(f"Built {len(pipelines)} pipeline(s): {[p.pipeline_id for p in pipelines]}")

    # ID consistency smoke test
    if not skip_smoke_test and hasattr(dataset, "corpus"):
        console.print("[bold]Running ID consistency smoke test...[/bold]")
        for pipeline in pipelines:
            await validate_id_consistency(pipeline, queries, dataset.corpus)
        console.print("[green]Smoke test passed.[/green]")

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
    metrics_rows = await store.get_metrics(run_id)
    await store.finish_run(run_id)

    # Print error samples if any errors occurred
    if runner.error_samples:
        from rich.panel import Panel
        console.print(Panel(
            "\n".join(f"• {e}" for e in runner.error_samples),
            title="[red]Errors (first unique messages)[/red]",
            border_style="red",
        ))

    # Print summary table
    _print_metrics_table(aggregated, run_id)

    # Print stage-by-stage contribution (delta between prefix/full pipelines)
    pipeline_ids = [p.pipeline_id for p in pipelines]
    _print_stage_contribution(aggregated, metrics_rows, pipeline_ids, latency_budget_ms)

    # Print diagnostic failure mode summary
    _print_diagnostics_summary(diagnostics)
    console.print(f"[dim]Tip: retobs inspect {run_id} --query <query_id> to debug individual failures.[/dim]")

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
    from retrieval_observatory.metrics.significance import benjamini_hochberg, paired_bootstrap_test
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)

    engine = MetricsEngine()
    agg1 = await engine.aggregate(run_id_1, store)
    agg2 = await engine.aggregate(run_id_2, store)

    all_keys = sorted(set(agg1.keys()) | set(agg2.keys()))

    metrics1 = await store.get_metrics(run_id_1)
    metrics2 = await store.get_metrics(run_id_2)

    # Compute all p-values first so we can apply BH correction across metrics
    row_data = []
    raw_p_values = []
    for key in all_keys:
        a1 = agg1.get(key, {})
        a2 = agg2.get(key, {})
        mean1 = f"{a1.get('mean', 0):.4f} ± {a1.get('std', 0):.4f}" if a1 else "—"
        mean2 = f"{a2.get('mean', 0):.4f} ± {a2.get('std', 0):.4f}" if a2 else "—"
        s1, s2, n_pairs = paired_scores_by_query(metrics1, metrics2, key)
        if s1 and s2:
            p = paired_bootstrap_test(s1, s2)
            raw_p_values.append(p)
            row_data.append((key, mean1, mean2, p, n_pairs))
        else:
            row_data.append((key, mean1, mean2, None, 0))

    q_values = benjamini_hochberg(raw_p_values)
    q_idx = 0

    table = Table(title=f"Run Comparison: {run_id_1} vs {run_id_2}")
    table.add_column("Metric", style="bold")
    table.add_column(run_id_1, justify="right")
    table.add_column(run_id_2, justify="right")
    table.add_column("p-value", justify="right")
    table.add_column("q-value (BH)", justify="right")

    for key, mean1, mean2, p, n_pairs in row_data:
        if p is not None:
            q = q_values[q_idx]
            q_idx += 1
            p_str = f"{p:.3f} ({n_pairs} pairs)"
            q_str = f"[bold]{q:.3f} *[/bold]" if q < 0.05 else f"{q:.3f}"
        else:
            p_str = "—"
            q_str = "—"
        table.add_row(key, mean1, mean2, p_str, q_str)

    console.print(table)
    console.print("[dim]q-value: Benjamini-Hochberg FDR-adjusted p-value. Use q < 0.05 for significance.[/dim]")


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


def _print_diagnostics_summary(diagnostics: list) -> None:
    if not diagnostics:
        return
    from collections import defaultdict

    # Aggregate by pipeline_id
    by_pipeline: dict = defaultdict(lambda: {"total": 0, "labels": defaultdict(int), "buckets": defaultdict(int)})
    for row in diagnostics:
        pid = row["pipeline_id"]
        by_pipeline[pid]["total"] += 1
        for label in row.get("failure_labels", []):
            by_pipeline[pid]["labels"][label] += 1
        by_pipeline[pid]["buckets"][row.get("difficulty_bucket", "unknown")] += 1

    table = Table(title="Diagnostics Summary")
    table.add_column("Pipeline", style="bold")
    table.add_column("Failure Modes", justify="left")
    table.add_column("Difficulty Buckets", justify="left")

    label_order = ["candidate_miss", "reranker_drop", "lexical_mismatch", "semantic_mismatch", "id_or_qrel_issue", "unstable"]
    for pid, data in sorted(by_pipeline.items()):
        total = data["total"]
        labels_str = "  ".join(
            f"{lbl}: {data['labels'][lbl]/total:.0%}"
            for lbl in label_order
            if data["labels"].get(lbl, 0) > 0
        ) or "none"
        buckets_str = "  ".join(
            f"{b}: {data['buckets'][b]/total:.0%}"
            for b in ["easy", "medium", "hard", "discriminative"]
            if data["buckets"].get(b, 0) > 0
        ) or "—"
        table.add_row(pid, labels_str, buckets_str)

    console.print(table)


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


def _print_stage_contribution(
    aggregated: dict,
    metrics_rows: list,
    pipeline_ids: list,
    latency_budget_ms: Optional[int] = None,
) -> None:
    from retrieval_observatory.metrics.comparison import parse_metric_key, pipeline_pairs
    from retrieval_observatory.metrics.significance import benjamini_hochberg, paired_bootstrap_test

    pairs = pipeline_pairs(pipeline_ids)
    if not pairs:
        return

    # Parse aggregated keys into {pipeline_id: {stage_index: [(mname, k, full_key)]}}
    keys_by_pipeline: dict = {}
    for key in aggregated:
        try:
            pid, sidx, mname, k = parse_metric_key(key)
        except Exception:
            continue
        keys_by_pipeline.setdefault(pid, {}).setdefault(sidx, []).append((mname, k, key))

    quality_metrics = {"recall", "ndcg", "mrr", "map"}

    for before_id, after_id in pairs:
        before_stages = keys_by_pipeline.get(before_id, {})
        after_stages = keys_by_pipeline.get(after_id, {})
        if not before_stages or not after_stages:
            continue

        before_last = max(s for s in before_stages if s >= 0)
        after_last = max(s for s in after_stages if s >= 0)

        before_quality = {(mname, k): full_key for mname, k, full_key in before_stages.get(before_last, []) if mname in quality_metrics}
        after_quality = {(mname, k): full_key for mname, k, full_key in after_stages.get(after_last, []) if mname in quality_metrics}
        shared_metrics = sorted(set(before_quality) & set(after_quality))

        row_data = []
        raw_p_values = []
        for mname, k in shared_metrics:
            b_mean = aggregated[before_quality[(mname, k)]]["mean"]
            a_mean = aggregated[after_quality[(mname, k)]]["mean"]
            delta = a_mean - b_mean
            pct = (delta / b_mean * 100) if b_mean != 0 else 0.0

            b_scores = {r["query_id"]: r["value"] for r in metrics_rows
                        if r["pipeline_id"] == before_id and r["stage_index"] == before_last
                        and r["metric_name"] == mname and r["k"] == k}
            a_scores = {r["query_id"]: r["value"] for r in metrics_rows
                        if r["pipeline_id"] == after_id and r["stage_index"] == after_last
                        and r["metric_name"] == mname and r["k"] == k}
            shared_qids = sorted(set(b_scores) & set(a_scores))
            if shared_qids:
                s1 = [b_scores[q] for q in shared_qids]
                s2 = [a_scores[q] for q in shared_qids]
                p = paired_bootstrap_test(s1, s2)
                raw_p_values.append(p)
                row_data.append((mname, k, b_mean, a_mean, delta, pct, p))
            else:
                row_data.append((mname, k, b_mean, a_mean, delta, pct, None))

        # Latency: stage_index=-1 for multi-stage, else max positive index
        def _lat_mean(pid: str, stages: dict) -> Optional[float]:
            lat_stage = -1 if -1 in stages else max((s for s in stages if s >= 0), default=None)
            if lat_stage is None:
                return None
            entries = [(mname, k, full_key) for mname, k, full_key in stages.get(lat_stage, []) if mname == "latency_p50"]
            return aggregated[entries[0][2]]["mean"] if entries and entries[0][2] in aggregated else None

        lat_before = _lat_mean(before_id, before_stages)
        lat_after = _lat_mean(after_id, after_stages)

        q_values = benjamini_hochberg(raw_p_values)
        q_idx = 0

        table = Table(title=f"Stage Contribution: {before_id} → {after_id}")
        table.add_column("Metric", style="bold")
        table.add_column("Before", justify="right")
        table.add_column("After", justify="right")
        table.add_column("Δ", justify="right")
        table.add_column("Significant?", justify="right")

        for mname, k, b_mean, a_mean, delta, pct, p in row_data:
            metric_label = f"{mname}@{k}" if k > 0 else mname
            delta_color = "green" if delta > 0 else "red"
            delta_str = f"[{delta_color}]{delta:+.4f} ({pct:+.1f}%)[/{delta_color}]"
            if p is not None:
                q = q_values[q_idx]
                q_idx += 1
                sig_str = f"[bold green]q={q:.3f} ✓[/bold green]" if q < 0.05 else f"q={q:.3f}"
            else:
                sig_str = "—"
            table.add_row(metric_label, f"{b_mean:.4f}", f"{a_mean:.4f}", delta_str, sig_str)

        if lat_before is not None and lat_after is not None:
            lat_delta = lat_after - lat_before
            lat_color = "red" if lat_delta > 0 else "green"
            lat_str = f"[{lat_color}]{lat_delta:+.0f}ms[/{lat_color}]"
            table.add_row("Latency P50", f"{lat_before:.0f}ms", f"{lat_after:.0f}ms", lat_str, "—")

        console.print(table)

        # Neutral summary + optional latency verdict
        best_quality = max(row_data, key=lambda r: abs(r[4]), default=None)
        if best_quality:
            mname, k, b_mean, a_mean, delta, pct, p = best_quality
            metric_label = f"{mname}@{k}" if k > 0 else mname
            q_verdict = ""
            if p is not None:
                q_val = q_values[q_idx - (len(raw_p_values) - [i for i, r in enumerate(row_data) if r[6] == p][0])] if raw_p_values else 1.0
                q_verdict = " ✓ significant" if q_val < 0.05 else " (not significant)"
            console.print(
                f"  {metric_label} changed {delta:+.4f} ({pct:+.1f}%){q_verdict}. "
                + (f"Latency cost: {lat_after - lat_before:+.0f}ms P50." if lat_before and lat_after else "")
            )
            if latency_budget_ms is not None and lat_before is not None and lat_after is not None:
                lat_delta = lat_after - lat_before
                if lat_delta <= latency_budget_ms:
                    console.print(f"  [green]Latency delta ({lat_delta:.0f}ms) is within your {latency_budget_ms}ms budget.[/green]")
                else:
                    over = lat_delta - latency_budget_ms
                    console.print(f"  [red]Latency delta ({lat_delta:.0f}ms) exceeds your {latency_budget_ms}ms budget by {over:.0f}ms.[/red]")
            elif lat_before is not None and lat_after is not None:
                console.print("  [dim]→ Adjust your latency budget in the dashboard (retobs serve) to explore tradeoffs.[/dim]")


@app.command()
def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
    query_id: str = typer.Option(..., "--query", "-q", help="Query ID to inspect"),
    pipeline_id: Optional[str] = typer.Option(None, "--pipeline", "-p", help="Pipeline ID (defaults to all)"),
    db_path: str = typer.Option(".retobs/results.db", "--db"),
) -> None:
    """Inspect retrieved documents for a specific query and pipeline."""
    asyncio.run(_inspect(run_id, query_id, pipeline_id, db_path))


async def _inspect(run_id: str, query_id: str, pipeline_id: Optional[str], db_path: str) -> None:
    import aiosqlite
    import json as _json

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Load stage rows for this query
        sql = """SELECT pipeline_id, stage_index, stage_id, status, latency_ms,
                        retrieved_doc_ids_json, retrieved_scores_json, error_traceback
                 FROM raw_results
                 WHERE run_id = ? AND query_id = ? AND stage_index >= 0
                 ORDER BY pipeline_id, stage_index"""
        params: tuple = (run_id, query_id)
        if pipeline_id:
            sql = sql.replace("AND stage_index >= 0", "AND pipeline_id = ? AND stage_index >= 0")
            params = (run_id, query_id, pipeline_id)

        async with db.execute(sql, params) as cur:
            stage_rows = await cur.fetchall()

        # Load diagnostics for this query
        diag_sql = "SELECT * FROM query_diagnostics WHERE run_id = ? AND query_id = ?"
        if pipeline_id:
            diag_sql += " AND pipeline_id = ?"
            diag_params: tuple = (run_id, query_id, pipeline_id)
        else:
            diag_params = (run_id, query_id)
        async with db.execute(diag_sql, diag_params) as cur:
            diag_rows = await cur.fetchall()

    diag_by_pipeline = {}
    for row in diag_rows:
        diag_by_pipeline[row["pipeline_id"]] = {
            "failure_labels": _json.loads(row["failure_labels_json"]),
            "difficulty_bucket": row["difficulty_bucket"],
            "missing_relevant_ids": set(_json.loads(row["missing_relevant_ids_json"])),
            "stage_hits": {k: set(v) for k, v in _json.loads(row["stage_hits_json"]).items()},
        }

    # Group by pipeline
    from collections import defaultdict
    by_pipeline: dict = defaultdict(list)
    for row in stage_rows:
        by_pipeline[row["pipeline_id"]].append(row)

    if not by_pipeline:
        console.print(f"[red]No results found for run={run_id} query={query_id}[/red]")
        return

    console.print(f"\n[bold]Run:[/bold] {run_id}  [bold]Query:[/bold] {query_id}\n")

    for pid, stages in sorted(by_pipeline.items()):
        diag = diag_by_pipeline.get(pid, {})
        labels = diag.get("failure_labels", [])
        bucket = diag.get("difficulty_bucket", "?")
        label_str = ", ".join(labels) if labels else "none"
        console.print(f"[bold cyan]Pipeline:[/bold cyan] {pid}  bucket={bucket}  labels=[yellow]{label_str}[/yellow]")

        for stage_row in stages:
            stage_idx = stage_row["stage_index"]
            doc_ids = _json.loads(stage_row["retrieved_doc_ids_json"])
            scores = _json.loads(stage_row["retrieved_scores_json"])
            hits_at_stage = diag.get("stage_hits", {}).get(str(stage_idx), set())

            table = Table(
                title=f"Stage {stage_idx}: {stage_row['stage_id']} ({stage_row['status']}, {stage_row['latency_ms']:.0f}ms)",
                show_header=True,
            )
            table.add_column("Rank", justify="right", width=5)
            table.add_column("Doc ID", style="bold")
            table.add_column("Score", justify="right", width=10)
            table.add_column("Relevant?", justify="center", width=10)

            for rank, (did, score) in enumerate(zip(doc_ids, scores), start=1):
                is_hit = did in hits_at_stage
                rel_str = "[green]YES[/green]" if is_hit else "[dim]—[/dim]"
                table.add_row(str(rank), did, f"{score:.4f}", rel_str)

            console.print(table)

        missing = diag.get("missing_relevant_ids", set())
        if missing:
            console.print(f"  [red]Missing relevant:[/red] {', '.join(sorted(missing))}\n")
        else:
            console.print()


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
    if output.exists() and not force:
        console.print(f"[red]Refusing to overwrite {output}. Pass --force to replace it.[/red]")
        raise typer.Exit(1)

    output.write_text(_starter_config_yaml(mode))
    console.print(f"[green]Wrote config:[/green] {output}")
    console.print(f"  Run [bold]retobs validate --config {output}[/bold] to check for issues before running.")

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


def _starter_config_yaml(mode: str) -> str:
    """Return a starter YAML config string with inline explanatory comments."""
    if mode == "beir":
        return """\
experiment:
  name: beir-nfcorpus-eval

dataset:
  type: beir
  name: beir/nfcorpus      # any of: nfcorpus, scifact, fiqa, trec-covid, nq, hotpotqa, ...
  split: test
  max_queries: 50           # set to null to use all queries (323 for nfcorpus)

stages:
  bm25:
    type: adapter.bm25
    config:
      k: 100                # how many candidates to retrieve (before any reranking)
  dense:
    type: adapter.hf_biencoder
    config:
      model: sentence-transformers/all-MiniLM-L6-v2  # any sentence-transformers model
      k: 100

combinations:
  include:
    - [bm25]
    - [dense]

metrics:
  recall_at_k: [1, 5, 10, 20]   # list of K values to evaluate
  ndcg_at_k: [10]
  mrr: true
  map: true

execution:
  concurrency: 4            # parallel (pipeline, query) tasks; increase for HTTP adapters
  timeout_seconds: 60       # per-query timeout; increase for slow models
  cache_results: true       # skip re-running queries with identical config

output:
  store: sqlite
  db_path: .retobs/results.db
  export: [json]            # also write a JSON file after the run
"""

    if mode == "http-endpoint":
        return """\
experiment:
  name: http-endpoint-eval

dataset:
  type: custom
  name: custom
  queries_path: retobs_sample_data/queries.jsonl
  corpus_path: retobs_sample_data/corpus.jsonl
  timestamp_field: timestamp          # optional: field in corpus docs for temporal recall
  metadata_fields: [source]           # optional: extra fields to group metrics by

pipelines:
  - id: http_retriever
    stages:
      - type: adapter.http
        url: http://localhost:8000/search    # POST {query, k} → {results: [{id, text, score}]}
        config:
          k: 10
          timeout_ms: 10000                  # per-request HTTP timeout

metrics:
  recall_at_k: [1, 5, 10]
  ndcg_at_k: [10]
  mrr: true
  map: true

execution:
  concurrency: 4
  timeout_seconds: 30
  cache_results: true

output:
  store: sqlite
  db_path: .retobs/results.db
"""

    # For bm25+dense, bm25+reranker, custom-jsonl
    stages_block = """\
stages:
  bm25:
    type: adapter.bm25
    config:
      k: 100                # candidates to retrieve
  dense:
    type: adapter.hf_biencoder
    config:
      model: sentence-transformers/all-MiniLM-L6-v2
      k: 100
  rerank:
    type: adapter.hf_crossencoder
    config:
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      k: 10                 # top-K to keep after reranking
"""

    if mode == "bm25+dense":
        extra_pipelines_block = """\
# RRF combines bm25 and dense via Reciprocal Rank Fusion.
# score(doc) = Σ 1/(60 + rank_i)  — must be defined explicitly (not via combinations).
pipelines:
  - id: rrf_hybrid
    stages:
      - type: adapter.rrf
        config:
          rrf_k: 60       # RRF smoothing constant (default 60)
          fetch_k: 100    # candidates fetched from each sub-retriever
          top_k: 100
          retrievers:
            - type: adapter.bm25
            - type: adapter.hf_biencoder
              config:
                model: sentence-transformers/all-MiniLM-L6-v2

"""
        combos = "  include:\n    - [bm25]\n    - [dense]\n"
    elif mode == "bm25+reranker":
        extra_pipelines_block = ""
        combos = "  include:\n    - [bm25, rerank]   # bm25 retrieves 100, reranker re-scores to top 10\n  ablations: true   # automatically also runs [bm25] alone for stage attribution\n"
    else:  # custom-jsonl
        extra_pipelines_block = ""
        combos = "  include:\n    - [bm25]\n"

    return f"""\
experiment:
  name: {mode}-eval

dataset:
  type: custom
  name: custom
  queries_path: retobs_sample_data/queries.jsonl   # JSONL: {{query_id, text, relevant_doc_ids}}
  corpus_path: retobs_sample_data/corpus.jsonl     # JSONL: {{id, title, text, timestamp, ...}}
  timestamp_field: timestamp     # corpus field used for temporal recall metrics (optional)
  metadata_fields: [source]      # corpus/query fields to group metric breakdowns by (optional)

{stages_block}
{extra_pipelines_block}# combinations expands stages into pipelines automatically.
# Each list in include is one pipeline: [stage_a] or [stage_a, stage_b] (retriever → reranker).
# ablations: true auto-generates prefix pipelines to measure per-stage contribution.
combinations:
{combos}
metrics:
  recall_at_k: [1, 5, 10, 20]   # K values for Recall@K
  ndcg_at_k: [10]
  mrr: true
  map: true

execution:
  concurrency: 4            # parallel tasks; set to 1 to debug
  timeout_seconds: 60       # per-query timeout across all stages
  cache_results: true       # reuse results when re-running with the same pipeline config

output:
  store: sqlite             # use "postgres" + postgres_dsn for team setups
  db_path: .retobs/results.db
  export: [json]
"""


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
    ablations = False
    if mode in {"bm25+dense", "beir"}:
        include = [["bm25"], ["dense"]]
    if mode == "bm25+reranker":
        include = [["bm25", "rerank"]]
        ablations = True
    return {
        "experiment": {"name": f"{mode}-eval"},
        "dataset": dataset,
        "stages": stages,
        "combinations": {"include": include, "ablations": ablations},
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
