from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="retobs", help="Retrieval Observatory — RAG pipeline benchmarking.")
mcp_app = typer.Typer(name="mcp", help="Run the MCP server and bootstrap agent integration.")
classifier_app = typer.Typer(name="classifier", help="Train and run query difficulty classifiers.")
forge_app = typer.Typer(name="forge", help="Generate corpus-specific stress-test evaluation datasets.")
tracelens_app = typer.Typer(name="tracelens", help="Production retrieval observability — inspect and monitor live traces.")
advisor_app = typer.Typer(name="advisor", help="Reliability advisor — regressions, recommendations, golden sets.")
app.add_typer(mcp_app, name="mcp")
app.add_typer(classifier_app, name="classifier")
app.add_typer(forge_app, name="forge")
app.add_typer(tracelens_app, name="tracelens")
app.add_typer(advisor_app, name="advisor")
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


async def _run(config_path: Path, skip_smoke_test: bool, no_cache: bool = False, latency_budget_ms: Optional[int] = None, golden_set: Optional[str] = None) -> None:
    from retrieval_observatory.config.schema import ExperimentConfig
    from retrieval_observatory.config.validator import validate_id_consistency
    from retrieval_observatory.datasets.beir import BEIRDataset
    from retrieval_observatory.datasets.custom import CustomDataset
    from retrieval_observatory.datasets.validation import validate_experiment_config
    from retrieval_observatory.pipeline.factory import build_pipeline_from_config
    from retrieval_observatory.runner.cache import StageResultCache
    from retrieval_observatory.runner.execute import execute_benchmark
    from retrieval_observatory.store.sqlite import SQLiteStore

    try:
        cfg = ExperimentConfig.from_yaml(str(config_path))
    except Exception as e:
        console.print(f"[red]Cannot parse config {config_path}: {e}[/red]")
        console.print("[dim]Run [bold]retobs validate --config <path>[/bold] for a detailed config check.[/dim]")
        raise typer.Exit(1)
    from retrieval_observatory.config.runtime import prepare_config_runtime

    prepare_config_runtime(cfg, config_path.parent)
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
    elif cfg.dataset.type == "custom" or cfg.dataset.name == "custom" or cfg.dataset.queries_path:
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

    # Wire a shared cross-pipeline stage cache into the pipeline objects at build time.
    stage_cache = StageResultCache(store=store) if (cfg.execution.cache_results and not no_cache) else None
    from retrieval_observatory.pipeline.factory import build_dag_from_config
    pipelines = [build_pipeline_from_config(p.model_dump(), corpus=corpus, stage_cache=stage_cache) for p in cfg.pipelines]
    pipelines += [build_dag_from_config(g.model_dump(), corpus=corpus) for g in cfg.graphs]
    console.print(f"Built {len(pipelines)} pipeline(s): {[p.pipeline_id for p in pipelines]}")

    # ID consistency smoke test
    if not skip_smoke_test and hasattr(dataset, "corpus"):
        console.print("[bold]Running ID consistency smoke test...[/bold]")
        for pipeline in pipelines:
            await validate_id_consistency(pipeline, queries, dataset.corpus)
        console.print("[green]Smoke test passed.[/green]")

    artifacts = await execute_benchmark(
        cfg=cfg,
        dataset=dataset,
        queries=queries,
        qrels=qrels,
        corpus=corpus,
        pipelines=pipelines,
        store=store,
        no_cache=no_cache,
        latency_budget_ms=latency_budget_ms,
        golden_set=golden_set,
        validation_report=validation_report,
        config_path=str(config_path),
        log=console.print,
    )
    run_id = artifacts.run_id
    aggregated = artifacts.aggregated
    metrics_rows = artifacts.metrics_rows
    diagnostics = artifacts.diagnostics
    pipeline_ids = artifacts.pipeline_ids

    # Print error samples if any errors occurred
    if artifacts.error_samples:
        from rich.panel import Panel
        console.print(Panel(
            "\n".join(f"• {e}" for e in artifacts.error_samples),
            title="[red]Errors (first unique messages)[/red]",
            border_style="red",
        ))

    # Print summary table
    _print_metrics_table(aggregated, run_id)
    _print_cost_table(cfg, pipeline_ids)

    # Print stage-by-stage contribution (delta between prefix/full pipelines)
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
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path"),
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


@app.command("diff-configs")
def diff_configs_cmd(
    config_a: Path = typer.Argument(..., help="Path to the 'before' experiment YAML config."),
    config_b: Path = typer.Argument(..., help="Path to the 'after' experiment YAML config."),
) -> None:
    """Structural diff between two pipeline configs: pipelines/stages added, removed, or changed."""
    from retrieval_observatory.config.diff import diff_configs
    from retrieval_observatory.config.schema import ExperimentConfig

    cfg_a = ExperimentConfig.from_yaml(str(config_a))
    cfg_b = ExperimentConfig.from_yaml(str(config_b))
    result = diff_configs(cfg_a, cfg_b)

    if not result.has_changes:
        console.print("[dim]No structural differences.[/dim]")
        return

    if result.dataset_changed:
        console.print("[yellow]Dataset config changed.[/yellow]")
    if result.metrics_changed:
        console.print("[yellow]Metrics config changed.[/yellow]")

    for pdiff in result.pipeline_diffs:
        if pdiff.change == "unchanged":
            continue
        console.print(f"[bold]{pdiff.pipeline_id}[/bold]: {pdiff.change}")
        for sdiff in pdiff.stage_diffs:
            if sdiff.change == "unchanged":
                continue
            console.print(f"  stage {sdiff.index}: {sdiff.change}")
            if sdiff.before:
                console.print(f"    before: {sdiff.before}")
            if sdiff.after:
                console.print(f"    after:  {sdiff.after}")


def _collect_dashboard_db_paths(cli_dbs: Optional[List[str]]) -> List[str]:
    """Merge repeated --db flags, comma-separated paths, and RETOBS_DASHBOARD_DBS."""
    paths: List[str] = []
    if cli_dbs:
        for arg in cli_dbs:
            for part in arg.split(","):
                p = part.strip()
                if p:
                    paths.append(p)
    env = os.environ.get("RETOBS_DASHBOARD_DBS")
    if env:
        for part in env.split(":"):
            p = part.strip()
            if p:
                paths.append(p)
    if not paths:
        paths = [".retobs/results.db"]
    return paths


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(4000, "--port"),
    db: Optional[List[str]] = typer.Option(None, "--db", "--db-path", help="SQLite DB path(s); repeat or comma-separate."),
) -> None:
    """Start the FastAPI dashboard server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[/red]")
        raise typer.Exit(1)

    db_paths = _collect_dashboard_db_paths(db)
    missing = [p for p in db_paths if not Path(p).exists()]
    if missing:
        for p in missing:
            console.print(f"[red]Database not found:[/red] {p}")
        raise typer.Exit(1)

    try:
        from retrieval_observatory.dashboard.api import create_app
        from retrieval_observatory.dashboard.registry import DbRegistry

        registry = DbRegistry(db_paths)
        dashboard_app = create_app(registry=registry)
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        console.print(f"[bold green]Dashboard:[/bold green] http://{display_host}:{port}")
        if len(db_paths) > 1:
            console.print(f"[dim]Loaded {len(db_paths)} databases: {', '.join(registry.list_db_ids())}[/dim]")
        uvicorn.run(dashboard_app, host=host, port=port)
    except ImportError:
        console.print("[red]Dashboard not available. Install fastapi: pip install fastapi uvicorn[/red]")
        raise typer.Exit(1)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@mcp_app.callback(invoke_without_command=True)
def mcp(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to an MCP YAML config file."),
) -> None:
    """Run the MCP server (stdio) exposing retobs benchmarking tools to agents."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        from retrieval_observatory.mcp.server import main as _mcp_main
    except ImportError:
        console.print("[red]MCP server requires the 'mcp' package. Install: pip install 'retrieval-observatory[mcp]'[/red]")
        raise typer.Exit(1)
    _mcp_main(str(config) if config else None)


@mcp_app.command("init")
def mcp_init(
    output: str = typer.Option("retobs-mcp.yaml", "--output", help="Path to write the starter MCP config."),
) -> None:
    """Create a starter MCP config file and print registration guidance for agents."""
    from retrieval_observatory.mcp.config import write_default_config

    path = write_default_config(output)
    console.print(f"[green]Wrote MCP config to[/green] {path}")
    console.print("Example registration:")
    console.print('{"mcpServers": {"retobs": {"command": "retobs", "args": ["mcp"]}}}')


@app.command("integrate")
def integrate_cmd(
    framework: str = typer.Option(..., "--framework", "-f", help="langchain|llamaindex|fastapi|http|python"),
    check: bool = typer.Option(False, "--check", help="Print verification steps after the snippet."),
) -> None:
    """Print the wiring snippet for instrumenting an existing pipeline."""
    from retrieval_observatory.integrations.registry import describe_integration

    guide = describe_integration(framework)
    if guide.get("error"):
        console.print(f"[red]{guide['error']}[/red]")
        console.print(f"Frameworks: {', '.join(guide.get('frameworks', []))}")
        raise typer.Exit(1)
    console.print(f"[bold]{guide['title']}[/bold]")
    if guide.get("install_extra"):
        console.print(f"Install extra: pip install 'retrieval-observatory[{guide['install_extra']}]'")
    if guide.get("env_vars"):
        console.print(f"Env: {', '.join(guide['env_vars'])}")
    console.print("\n[bold]Snippet[/bold]\n")
    console.print(guide["snippet"])
    if check:
        console.print("\n[bold]Verify[/bold]")
        console.print(guide.get("verify", ""))
        console.print("Then: retobs doctor && retobs mcp (verify_integration tool)")


@app.command("doctor")
def doctor_cmd(
    db: str = typer.Option(".retobs/results.db", "--db", help="SQLite DB to probe."),
) -> None:
    """Check local retobs install: extras, DB, dashboard build, MCP registration."""
    import importlib.util
    from pathlib import Path

    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        if not passed:
            ok = False
        mark = "[green]✓[/green]" if passed else "[red]✗[/red]"
        console.print(f"{mark} {label}" + (f" — {detail}" if detail else ""))

    check("retrieval_observatory import", True)
    check("numpy", importlib.util.find_spec("numpy") is not None)
    check("fastapi (dashboard)", importlib.util.find_spec("fastapi") is not None)
    check("mcp server", importlib.util.find_spec("mcp") is not None, "optional: pip install 'retrieval-observatory[mcp]'")

    ui_dist = Path(__file__).resolve().parent / "dashboard" / "ui" / "dist" / "index.html"
    check("dashboard UI build", ui_dist.is_file(), str(ui_dist))

    db_path = Path(db)
    check("database reachable", db_path.is_file() or not db_path.exists(), "missing file is OK until first run")

    try:
        from retrieval_observatory.mcp.server import build_server

        srv = build_server()
        import asyncio

        tools = asyncio.run(srv.list_tools())
        names = {t.name for t in tools}
        check("MCP tools registered", "benchmark_config" in names and "describe_integration" in names, f"{len(names)} tools")
    except Exception as e:
        check("MCP tools registered", False, str(e))

    if not ok:
        raise typer.Exit(1)
    console.print("[green]All checks passed.[/green]")


@app.command()
def diagram(
    run_id: str = typer.Argument(..., help="Run ID to render."),
    output: str = typer.Option("diagram.html", "--output", "-o", help="Output HTML file path."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
) -> None:
    """Export a read-only pipeline diagram (per-stage metrics + CIs) as a standalone HTML file."""
    asyncio.run(_diagram(run_id, output, db))


async def _diagram(run_id: str, output: str, db_path: str) -> None:
    from retrieval_observatory.dashboard.api import _build_diagram, _pipeline_results_from_traces
    from retrieval_observatory.diagram.html import render_diagram_html
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    metrics = await MetricsEngine().aggregate(run_id, store)
    if not metrics:
        console.print(f"[red]Run '{run_id}' not found or has no metrics in {db_path}.[/red]")
        raise typer.Exit(1)
    traces = await store.get_traces_v2(run_id) if hasattr(store, "get_traces_v2") else []
    results = _pipeline_results_from_traces(traces) if traces else await store.get_results(run_id)
    pipelines = _build_diagram(metrics, results)
    html = render_diagram_html(run_id, pipelines)
    with open(output, "w") as f:
        f.write(html)
    console.print(f"[green]Wrote diagram → {output}[/green] ({len(pipelines)} pipeline(s))")


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


def _print_cost_table(cfg, pipeline_ids: list) -> None:
    from retrieval_observatory.config.cost import pipeline_cost_per_1k

    costs = cfg.costs or {}
    if not costs:
        console.print("[dim]No config.costs — estimated cost omitted (dashboard Pareto cost views disabled).[/dim]")
        return

    table = Table(title="Estimated cost (from config)")
    table.add_column("Pipeline", style="bold")
    table.add_column("$/1k queries", justify="right")
    table.add_column("Source", style="dim")

    for pid in pipeline_ids:
        amount = pipeline_cost_per_1k(cfg, pid, costs)
        table.add_row(pid, f"{amount:.4f}", "config.costs per stage")

    console.print(table)
    console.print("[dim]Estimated from config.costs — not measured runtime spend.[/dim]")


def _print_metrics_table(aggregated: dict, run_id: str) -> None:
    table = Table(title=f"Results — Run {run_id}")
    table.add_column("Metric", style="bold")
    table.add_column("Mean", justify="right")
    table.add_column("Std", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("N", justify="right")

    for key, vals in sorted(aggregated.items()):
        ci_low, ci_high = vals.get("ci_low"), vals.get("ci_high")
        if ci_low is None or ci_high is None:
            ci = "—"
        else:
            ci = f"[{ci_low:.4f}, {ci_high:.4f}]"
        std = vals.get("std")
        std_str = "—" if std is None else f"{std:.4f}"
        table.add_row(
            key,
            f"{vals['mean']:.4f}",
            std_str,
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
            pid, sidx, mname, k, branch_id = parse_metric_key(key)
            if branch_id:
                continue
        except Exception:
            continue
        keys_by_pipeline.setdefault(pid, {}).setdefault(sidx, []).append((mname, k, key))

    quality_metrics = {"recall", "precision", "ndcg", "mrr", "map"}

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
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path"),
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
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="Optional SQLite DB for saving the report."),
) -> None:
    """Validate a benchmark config before running it."""
    from retrieval_observatory.config.schema import ExperimentConfig
    from retrieval_observatory.datasets.validation import validate_experiment_config
    from retrieval_observatory.store.sqlite import SQLiteStore

    try:
        cfg = ExperimentConfig.from_yaml(str(config))
    except Exception as e:
        console.print(f"[red]Cannot parse config {config}: {e}[/red]")
        raise typer.Exit(1)
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
    mode: str = typer.Option("custom-jsonl", "--mode", help="beir, custom-jsonl, http-endpoint, bm25+dense, bm25+reranker, reliability-demo"),
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
    if mode == "reliability-demo":
        return """\
# Starter config for the retobs reliability demo Forge dataset.
# Run: retobs demo  then point these paths at .retobs/demo/forge_dataset/

experiment:
  name: my-forge-stress-eval

dataset:
  type: custom
  name: custom
  queries_path: .retobs/demo/forge_dataset/queries.jsonl
  corpus_path: .retobs/demo/forge_dataset/corpus.jsonl

stages:
  bm25:
    type: adapter.bm25
    config:
      k: 20

combinations:
  include:
    - [bm25]

metrics:
  recall_at_k: [5, 10, 20]
  ndcg_at_k: [10]
  mrr: true

output:
  store: sqlite
  db_path: .retobs/demo/results.db
"""

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
    from retrieval_observatory.config.runtime import resolve_config_paths

    resolve_config_paths(cfg, base_dir)


def _print_classifier_report(report) -> None:
    console.print(f"\n[bold]Dataset:[/bold] {report.dataset_name or '(unknown)'}")
    console.print(f"[bold]Samples:[/bold] {report.n_samples}")
    console.print(f"[bold]Calibrated:[/bold] {'yes' if report.calibrated else 'no'}")
    for w in report.warnings:
        console.print(f"[yellow]{w}[/yellow]")

    dist_table = Table(title="Class Distribution")
    dist_table.add_column("Class")
    dist_table.add_column("Count", justify="right")
    for cls, count in sorted(report.class_distribution.items()):
        dist_table.add_row(cls, str(count))
    console.print(dist_table)

    metrics_table = Table(title="Cross-Validation Metrics (out-of-fold)")
    metrics_table.add_column("Metric")
    metrics_table.add_column("Value", justify="right")
    metrics_table.add_row("Accuracy", f"{report.cv_accuracy:.3f}")
    metrics_table.add_row("Macro F1", f"{report.cv_macro_f1:.3f}")
    metrics_table.add_row("Brier score", f"{report.cv_brier:.4f}")
    console.print(metrics_table)

    if report.feature_importances:
        imp_table = Table(title="Feature Importances (permutation)")
        imp_table.add_column("Rank", justify="right")
        imp_table.add_column("Feature")
        imp_table.add_column("Importance", justify="right")
        for i, (name, val) in enumerate(report.feature_importances, start=1):
            imp_table.add_row(str(i), name, f"{val:.4f}")
        console.print(imp_table)


@classifier_app.command("train")
def classifier_train(
    dataset: str = typer.Option(..., "--dataset", help="Dataset name (e.g. beir/nfcorpus). Required."),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path"),
    out: Optional[Path] = typer.Option(None, "--out", help="Model output path."),
    min_samples: int = typer.Option(30, "--min-samples"),
    min_per_class: int = typer.Option(5, "--min-per-class", help="Minimum samples per present class."),
) -> None:
    """Train a query difficulty classifier from stored diagnostics."""
    asyncio.run(_classifier_train(dataset, db_path, out, min_samples, min_per_class))


async def _classifier_train(
    dataset: str,
    db_path: str,
    out: Optional[Path],
    min_samples: int,
    min_per_class: int,
) -> None:
    from retrieval_observatory.classifier.data import load_labeled_queries
    from retrieval_observatory.classifier.labels import default_model_path
    from retrieval_observatory.classifier.model import train_model
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    runs = await store.list_runs_for_dataset(dataset)
    if not runs:
        console.print(
            f"[red]No benchmark runs found for dataset '{dataset}' in {db_path}.[/red]\n"
            "[dim]Run a benchmark first, e.g.: retobs run --config examples/advanced/dashboard_demo/config.yaml[/dim]"
        )
        raise typer.Exit(1)
    samples = await load_labeled_queries(store, dataset)
    if not samples:
        diag_count = sum(len(await store.get_query_diagnostics(r["run_id"])) for r in runs)
        console.print(
            f"[red]No labeled queries found for dataset '{dataset}' ({len(runs)} run(s) in {db_path}).[/red]"
        )
        if diag_count == 0:
            console.print(
                "[dim]query_diagnostics is empty — the benchmark likely failed before completion. "
                "Check: retobs validate --config <your-config.yaml>[/dim]"
            )
        raise typer.Exit(1)

    out_path = str(out) if out else default_model_path(dataset)
    try:
        report = train_model(samples, dataset, out_path, min_samples=min_samples, min_per_class=min_per_class)
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _print_classifier_report(report)
    console.print(f"\n[green]Model saved to {report.model_path}[/green]")


@classifier_app.command("predict")
def classifier_predict(
    query: str = typer.Option(..., "--query", help="Query text to classify."),
    model: Path = typer.Option(..., "--model", help="Path to trained model."),
) -> None:
    """Predict query difficulty from text."""
    try:
        from retrieval_observatory.classifier.model import load_model
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    m = load_model(str(model))
    pred = m.predict(query)
    console.print(f"[bold]Predicted:[/bold] {pred['label']}")
    console.print(f"[bold]Probabilities:[/bold] {json.dumps(pred['proba'], indent=2)}")

    drivers = Table(title="Top Feature Drivers")
    drivers.add_column("Feature")
    drivers.add_column("Value", justify="right")
    drivers.add_column("Importance", justify="right")
    for d in pred["top_drivers"]:
        drivers.add_row(d["feature"], f"{d['value']:.3f}", f"{d['importance']:.4f}")
    console.print(drivers)


@classifier_app.command("report")
def classifier_report(
    dataset: str = typer.Option(..., "--dataset", help="Dataset name used for training labels."),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path"),
    model: Optional[Path] = typer.Option(None, "--model", help="Path to saved model for importances."),
) -> None:
    """Print cross-validation metrics and feature importances."""
    asyncio.run(_classifier_report(dataset, db_path, model))


async def _classifier_report(
    dataset: str,
    db_path: str,
    model: Optional[Path],
) -> None:
    from retrieval_observatory.classifier.data import load_labeled_queries
    from retrieval_observatory.classifier.labels import default_model_path
    from retrieval_observatory.classifier.model import report_from_samples
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    samples = await load_labeled_queries(store, dataset)
    model_path = str(model) if model else default_model_path(dataset)
    try:
        report = report_from_samples(samples, model_path if Path(model_path).exists() else None)
        report.dataset_name = report.dataset_name or dataset
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _print_classifier_report(report)


# ---------------------------------------------------------------------------
# Forge commands — synthetic evaluation dataset generation
# ---------------------------------------------------------------------------

def _load_corpus_from_jsonl(corpus_path: str) -> dict:
    """Load corpus from JSONL file into {doc_id: {text, title}} dict."""
    import json as _json
    corpus = {}
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = _json.loads(line)
            doc_id = doc.get("id") or doc.get("_id") or doc.get("doc_id")
            if doc_id:
                corpus[str(doc_id)] = {
                    "text": doc.get("text", ""),
                    "title": doc.get("title", ""),
                }
    return corpus


@forge_app.command("scan")
def forge_scan(
    corpus: Path = typer.Option(..., "--corpus", help="Path to corpus.jsonl file."),
    scenario_types: str = typer.Option("temporal,alias", "--scenario-types", help="Comma-separated scenario types to detect."),
    max_per_type: int = typer.Option(30, "--max-per-type", help="Max scenarios to detect per type."),
) -> None:
    """Scan a corpus for retrieval failure scenarios — no LLM or API key needed.

    This is the dry-run step. Use it to preview what scenarios Forge found before
    spending any LLM budget on query generation.
    """
    from retrieval_observatory.forge.scenarios.registry import detect_all

    console.print(f"[bold]Forge Scan:[/bold] {corpus}")
    corp = _load_corpus_from_jsonl(str(corpus))
    console.print(f"Loaded [bold]{len(corp)}[/bold] documents.")

    types = [t.strip() for t in scenario_types.split(",") if t.strip()]
    scenarios = detect_all(corp, types=types, max_per_type=max_per_type)

    if not scenarios:
        console.print("[yellow]No scenarios detected. Try a larger or more diverse corpus.[/yellow]")
        return

    table = Table(title=f"Detected Scenarios ({len(scenarios)} total)", show_lines=True)
    table.add_column("Type", style="cyan", width=12)
    table.add_column("ID", style="dim", width=16)
    table.add_column("Docs", width=6)
    table.add_column("Evidence", no_wrap=False)

    by_type: dict = {}
    for s in scenarios:
        by_type[s.scenario_type] = by_type.get(s.scenario_type, 0) + 1
        table.add_row(
            s.scenario_type,
            s.scenario_id,
            str(len(s.anchor_doc_ids)),
            s.evidence_summary[:120] + ("…" if len(s.evidence_summary) > 120 else ""),
        )

    console.print(table)
    for t, count in by_type.items():
        console.print(f"  [green]{t}:[/green] {count} scenario(s)")
    console.print(f"\n[dim]Run [bold]retobs forge run --corpus {corpus}[/bold] to generate queries from these scenarios.[/dim]")


@forge_app.command("run")
def forge_run(
    corpus: Path = typer.Option(..., "--corpus", help="Path to corpus.jsonl file."),
    output: Path = typer.Option(..., "--output", "-o", help="Output directory for the generated dataset."),
    scenario_types: str = typer.Option("temporal,alias", "--scenario-types", help="Comma-separated scenario types."),
    query_types: str = typer.Option("paraphrase", "--query-types", help="Comma-separated: paraphrase,temporal,adversarial,comparison,constraint,long_tail."),
    n_per_type: int = typer.Option(3, "--n-per-type", help="Queries generated per scenario per query type."),
    n_queries: Optional[int] = typer.Option(None, "--n-queries", help="Total query budget (caps generation). Overrides n-per-type if smaller."),
    llm_provider: str = typer.Option("gemini", "--llm-provider", help="LLM provider: gemini (default, free), openai, anthropic."),
    llm_model: Optional[str] = typer.Option(None, "--llm-model", help="Model name override (default depends on provider)."),
    llm_budget: int = typer.Option(500, "--budget", help="Max LLM API calls for generation."),
    validate: bool = typer.Option(False, "--validate", help="Run LLM validation pass to expand qrels beyond extractive labels."),
    validation_budget: int = typer.Option(300, "--validation-budget", help="Max LLM calls for the validation pass."),
    fmt: str = typer.Option("beir", "--format", help="Output format: beir (default) or custom."),
    max_per_type: int = typer.Option(30, "--max-scenarios", help="Max scenarios to detect per scenario type."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="Store DB to register the dataset in (so it appears in the dashboard)."),
) -> None:
    """Generate a corpus-specific stress-test evaluation dataset using Forge.

    Step 1: Scans your corpus for failure patterns (temporal confusion, alias mismatches).
    Step 2: Uses an LLM to generate targeted hard queries for each scenario.
    Step 3: Builds extractive ground truth (source doc = relevant).
    Step 4: Exports as a BEIR-compatible dataset you can benchmark against.

    Requires: GOOGLE_API_KEY (default), OPENAI_API_KEY, or ANTHROPIC_API_KEY.
    """
    asyncio.run(_forge_run(
        corpus_path=str(corpus),
        output_dir=str(output),
        scenario_types=[t.strip() for t in scenario_types.split(",") if t.strip()],
        query_types=[t.strip() for t in query_types.split(",") if t.strip()],
        n_per_type=n_per_type,
        n_queries=n_queries,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_budget=llm_budget,
        validate=validate,
        validation_budget=validation_budget,
        fmt=fmt,
        max_per_type=max_per_type,
        db_path=db,
    ))


async def _forge_run(
    corpus_path: str,
    output_dir: str,
    scenario_types: list,
    query_types: list,
    n_per_type: int,
    n_queries: Optional[int],
    llm_provider: str,
    llm_model: Optional[str],
    llm_budget: int,
    validate: bool,
    validation_budget: int,
    fmt: str,
    max_per_type: int,
    db_path: str = ".retobs/results.db",
) -> None:
    from retrieval_observatory.forge.engine import ForgeEngine
    from retrieval_observatory.forge.generation.generator import ForgeGenerator
    from retrieval_observatory.forge.stress.suite import StressTestSuite

    console.print(f"[bold green]Forge:[/bold green] Loading corpus from {corpus_path}")
    corp = _load_corpus_from_jsonl(corpus_path)
    console.print(f"Loaded [bold]{len(corp)}[/bold] documents.")

    # Scenario scan first (free)
    console.print("[bold]Step 1/4:[/bold] Scanning corpus for failure scenarios...")
    from retrieval_observatory.forge.scenarios.registry import detect_all
    scenarios = detect_all(corp, types=scenario_types, max_per_type=max_per_type)
    console.print(f"  Found [bold]{len(scenarios)}[/bold] scenario(s).")
    if not scenarios:
        console.print("[yellow]No scenarios found. Your corpus may be too small or homogeneous.[/yellow]")
        console.print("[dim]Tip: Try a corpus with 100+ documents spanning multiple time periods or using abbreviations.[/dim]")
        return

    # Compute budget-adjusted n_per_type
    effective_n = n_per_type
    if n_queries is not None:
        total_gen_calls = len(scenarios) * len(query_types)
        if total_gen_calls > 0:
            effective_n = max(1, n_queries // total_gen_calls)

    console.print(f"[bold]Step 2/4:[/bold] Generating queries ({llm_provider} / {llm_model or 'default'})...")
    try:
        generator = ForgeGenerator.from_provider(
            provider=llm_provider,
            model=llm_model,
            budget=llm_budget,
        )
    except (ValueError, ImportError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    engine = ForgeEngine(
        corpus=corp,
        generator=generator,
        scenario_types=scenario_types,
        max_scenarios_per_type=max_per_type,
    )

    judge = None
    if validate:
        console.print("[bold]Step 3/4:[/bold] LLM validation pass enabled — expanding qrels...")
        try:
            from retrieval_observatory.datasets.llm_judge import GeminiJudge, OpenAIJudge, AnthropicJudge
            if llm_provider == "gemini":
                judge = GeminiJudge(model=llm_model or "gemini-2.0-flash")
            elif llm_provider == "openai":
                judge = OpenAIJudge(model=llm_model or "gpt-4o-mini")
            else:
                judge = AnthropicJudge(model=llm_model or "claude-haiku-4-5-20251001")
        except Exception as e:
            console.print(f"[yellow]Warning: could not init LLM judge for validation: {e}[/yellow]")
    else:
        console.print("[bold]Step 3/4:[/bold] Building extractive ground truth (no LLM needed)...")

    dataset = await engine.run(
        query_types=query_types,
        n_per_type=effective_n,
        validate=validate,
        judge=judge,
        validation_budget=validation_budget,
        output_dir=output_dir,
        output_format=fmt,
    )

    console.print(f"[bold]Step 4/4:[/bold] Exporting dataset → {output_dir}")

    suite = StressTestSuite(dataset)
    summary = suite.summary()

    table = Table(title="Forge Dataset Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Total queries", str(summary["total_queries"]))
    table.add_row("Total scenarios", str(summary["total_scenarios"]))
    table.add_row("Corpus documents", str(summary["corpus_size"]))
    table.add_row("Validated (LLM)", str(summary["validated"]))
    for diff, count in summary["by_difficulty"].items():
        table.add_row(f"  Difficulty: {diff}", str(count))
    for qtype, count in summary["by_query_type"].items():
        table.add_row(f"  Query type: {qtype}", str(count))
    console.print(table)

    # Register the dataset in the store so it shows up in the dashboard's Forge workspace.
    try:
        from retrieval_observatory.store.sqlite import SQLiteStore
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        await store.save_forge_dataset(
            dataset_id=dataset.dataset_id,
            summary_json=json.dumps(summary),
            corpus_path=corpus_path,
            output_dir=output_dir,
        )
        await store.save_forge_scenarios(
            dataset.dataset_id,
            json.dumps([
                {
                    "scenario_id": s.scenario_id,
                    "scenario_type": s.scenario_type,
                    "anchor_doc_ids": s.anchor_doc_ids,
                    "evidence_summary": s.evidence_summary,
                }
                for s in dataset.scenarios
            ]),
        )
        await store.save_forge_queries(
            dataset.dataset_id,
            json.dumps([
                {
                    "query_id": q.query_id,
                    "text": q.text,
                    "scenario_id": q.scenario_id,
                    "query_type": q.query_type,
                    "difficulty_label": q.difficulty_label,
                    "failure_category": q.failure_category,
                    "validated": q.validated,
                    "positive_doc_ids": q.positive_doc_ids,
                }
                for q in dataset.queries
            ]),
        )
        console.print(f"[dim]Registered dataset {dataset.dataset_id} in {db_path} (visible in dashboard).[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: could not register dataset in store: {e}[/yellow]")

    console.print(f"\n[green]Dataset saved to:[/green] {output_dir}")
    console.print(f"[dim]LLM calls used: {generator.calls_used} / {generator.budget}[/dim]")
    console.print(
        "\n[dim]Tip: Use this dataset with retobs run by pointing your config to the exported corpus.jsonl and queries.jsonl.[/dim]"
    )


@forge_app.command("list")
def forge_list(
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite DB to read from."),
) -> None:
    """List Forge datasets registered in the store."""
    asyncio.run(_forge_list(db))


async def _forge_list(db_path: str) -> None:
    from retrieval_observatory.store.sqlite import SQLiteStore

    if not Path(db_path).exists():
        console.print(f"[red]Database not found:[/red] {db_path}")
        console.print("[dim]Run 'retobs demo' to create a demo database, or 'retobs forge run' to generate a dataset.[/dim]")
        return

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    datasets = await store.get_forge_datasets()

    if not datasets:
        console.print(f"[yellow]No Forge datasets in {db_path}.[/yellow]")
        console.print("[dim]Run: retobs forge run --corpus <corpus.jsonl> --output <dir> --db " + db_path + "[/dim]")
        return

    table = Table(title=f"Forge Datasets — {db_path}", show_header=True)
    table.add_column("Dataset ID", style="bold cyan")
    table.add_column("Created", style="dim")
    table.add_column("Scenarios", justify="right")
    table.add_column("Queries", justify="right")
    table.add_column("Validated", justify="right")
    table.add_column("Corpus Path", style="dim")

    for d in datasets:
        s = d.get("summary", {})
        created = (d.get("created_at") or "")[:19]
        corpus_path = str(d.get("corpus_path") or "")
        corpus_short = ("…" + corpus_path[-38:]) if len(corpus_path) > 40 else corpus_path
        table.add_row(
            d["dataset_id"],
            created,
            str(s.get("n_scenarios", "?")),
            str(s.get("n_queries", "?")),
            str(s.get("validated", 0)),
            corpus_short,
        )

    console.print(table)
    console.print(f"[dim]{len(datasets)} dataset(s). Use 'retobs serve --db {db_path}' to explore in the dashboard.[/dim]")


# ---------------------------------------------------------------------------
# Demo command — full end-to-end synthetic pipeline, no API keys needed
# ---------------------------------------------------------------------------

@app.command()
def demo(
    output_dir: Path = typer.Option(Path(".retobs/demo"), "--output-dir", "-o", help="Directory for all demo outputs."),
    db: str = typer.Option(".retobs/demo/results.db", "--db", "--db-path", help="SQLite DB to write all data into."),
    service: str = typer.Option("demo", "--service", help="TraceLens service name for synthetic traces."),
    n_traces: int = typer.Option(300, "--n-traces", help="Synthetic TraceLens traces to seed."),
    keep_db: bool = typer.Option(False, "--keep-db", help="Append to existing DB instead of starting fresh."),
    full: bool = typer.Option(False, "--full", help="Also run multi-stage BM25+rereank ablation benchmark."),
) -> None:
    """Build a full reliability-platform demo: Forge → baseline + degraded benchmarks → TraceLens → Advisor.

    No API keys required. Seeds flawed/degraded data so all four dashboard modes are worth exploring.

    After completion: retobs serve --db <db>  →  http://localhost:4000
    """
    asyncio.run(_demo(
        output_dir=str(output_dir),
        db_path=db,
        tracelens_service=service,
        n_traces=n_traces,
        keep_db=keep_db,
        full=full,
    ))


async def _demo(
    output_dir: str,
    db_path: str,
    tracelens_service: str,
    n_traces: int,
    keep_db: bool = False,
    full: bool = False,
) -> None:
    from retrieval_observatory.forge.types import SyntheticDataset
    from retrieval_observatory.forge.datasets.exporter import export_dataset
    from retrieval_observatory.forge.scenarios.registry import detect_all
    from retrieval_observatory.store.sqlite import SQLiteStore

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    db_path_obj = Path(db_path)
    if db_path_obj.exists() and not keep_db:
        db_path_obj.unlink()
        console.print(f"[dim]Removed existing demo DB: {db_path}[/dim]")

    # ── Step 1: Write synthetic corpus ──────────────────────────────────────
    console.print("\n[bold cyan]Step 1/8[/bold cyan] Building synthetic RAG-domain corpus...")
    corpus_docs = _demo_corpus_docs()
    corpus_path = out / "corpus.jsonl"
    corpus_path.write_text("\n".join(json.dumps(d) for d in corpus_docs), encoding="utf-8")
    corpus_dict = {d["id"]: {"text": d["text"], "title": d["title"]} for d in corpus_docs}
    console.print(f"  [green]✓[/green] {len(corpus_docs)} documents → {corpus_path}")

    # ── Step 2: Forge scan (real detector, no LLM) ───────────────────────────
    console.print("\n[bold cyan]Step 2/8[/bold cyan] Scanning corpus for failure scenarios (no LLM)...")
    scenarios = detect_all(corpus_dict, types=["temporal", "alias"], max_per_type=20)
    temporal = [s for s in scenarios if s.scenario_type == "temporal"]
    alias = [s for s in scenarios if s.scenario_type == "alias"]
    console.print(f"  [green]✓[/green] {len(scenarios)} scenarios detected — {len(temporal)} temporal, {len(alias)} alias")
    if not scenarios:
        console.print("[yellow]  No scenarios detected. Check corpus content.[/yellow]")

    # ── Step 3: Build synthetic queries (no LLM) ─────────────────────────────
    console.print("\n[bold cyan]Step 3/8[/bold cyan] Building synthetic queries (hand-crafted, no LLM)...")
    synthetic_queries, qrels = _build_demo_queries(scenarios, corpus_dict)
    console.print(f"  [green]✓[/green] {len(synthetic_queries)} queries ({len(qrels)} with qrels)")

    # ── Step 4: Export Forge dataset and register in store ────────────────────
    console.print("\n[bold cyan]Step 4/8[/bold cyan] Exporting Forge dataset and registering in store...")
    forge_dir = out / "forge_dataset"
    dataset = SyntheticDataset(
        dataset_id="demo",
        corpus=corpus_dict,
        queries=synthetic_queries,
        qrels=qrels,
        scenarios=scenarios,
        metadata={"source": "retobs demo"},
    )
    export_dataset(dataset, str(forge_dir), fmt="custom")
    summary = dataset.summary()

    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    await store.save_forge_dataset(
        dataset_id=dataset.dataset_id,
        summary_json=json.dumps(summary),
        corpus_path=str(corpus_path.resolve()),
        output_dir=str(forge_dir.resolve()),
    )
    await store.save_forge_scenarios(
        dataset.dataset_id,
        json.dumps([
            {"scenario_id": s.scenario_id, "scenario_type": s.scenario_type,
             "anchor_doc_ids": s.anchor_doc_ids, "evidence_summary": s.evidence_summary}
            for s in scenarios
        ]),
    )
    await store.save_forge_queries(
        dataset.dataset_id,
        json.dumps([
            {"query_id": q.query_id, "text": q.text, "scenario_id": q.scenario_id,
             "query_type": q.query_type, "difficulty_label": q.difficulty_label,
             "failure_category": q.failure_category, "validated": q.validated,
             "positive_doc_ids": q.positive_doc_ids}
            for q in synthetic_queries
        ]),
    )
    console.print(f"  [green]✓[/green] Forge dataset 'demo' registered in {db_path}")
    console.print(f"         {summary['n_scenarios']} scenarios, {summary['n_queries']} queries, "
                  f"difficulty mix: {summary.get('queries_by_difficulty', {})}")

    # ── Step 5: Baseline BM25 benchmark (healthy k) ─────────────────────────
    console.print("\n[bold cyan]Step 5/8[/bold cyan] Running baseline BM25 benchmark (k=20)...")
    baseline_config = out / "benchmark_baseline.yaml"
    degraded_config = out / "benchmark_degraded.yaml"
    queries_path = str((forge_dir / "queries.jsonl").resolve())
    corpus_path = str((forge_dir / "corpus.jsonl").resolve())
    baseline_config.write_text(
        _demo_config_yaml(queries_path, corpus_path, db_path, k=20, experiment_name="forge-stress-baseline"),
        encoding="utf-8",
    )
    degraded_config.write_text(
        _demo_config_yaml(queries_path, corpus_path, db_path, k=1, experiment_name="forge-stress-degraded"),
        encoding="utf-8",
    )
    (out / "benchmark_config.yaml").write_text(baseline_config.read_text(encoding="utf-8"), encoding="utf-8")
    await _run(baseline_config, skip_smoke_test=True, no_cache=False, latency_budget_ms=800)

    runs = await store.list_runs()
    baseline_run_id = runs[0]["run_id"] if runs else "?"
    console.print(f"  [green]✓[/green] Baseline run: [bold]{baseline_run_id}[/bold]")

    # ── Step 6: Degraded BM25 benchmark (starved k) ───────────────────────────
    console.print("\n[bold cyan]Step 6/8[/bold cyan] Running degraded BM25 benchmark (k=1) for Advisor regression demo...")
    await _run(degraded_config, skip_smoke_test=True, no_cache=True, latency_budget_ms=800)

    runs = await store.list_runs()
    candidate_run_id = runs[0]["run_id"] if runs else "?"
    console.print(f"  [green]✓[/green] Degraded run: [bold]{candidate_run_id}[/bold]")

    ablation_run_id: Optional[str] = None
    if full:
        console.print("\n[bold cyan]Step 6b[/bold cyan] Running multi-stage ablation benchmark (BM25 + rerank)...")
        ablation_config = out / "benchmark_ablation.yaml"
        ablation_config.write_text(
            _demo_ablation_config_yaml(queries_path, corpus_path, db_path),
            encoding="utf-8",
        )
        await _run(ablation_config, skip_smoke_test=True, no_cache=True, latency_budget_ms=800)
        runs = await store.list_runs()
        ablation_run_id = runs[0]["run_id"] if runs else None
        console.print(f"  [green]✓[/green] Ablation run: [bold]{ablation_run_id}[/bold]")

    # ── Step 7: Seed TraceLens with drift + failure hotspots ──────────────────
    console.print(f"\n[bold cyan]Step 7/8[/bold cyan] Seeding {n_traces} showcase TraceLens traces (drift + hotspots)...")
    await _seed_showcase_traces(tracelens_service, n_traces, db_path)

    # ── Step 8: Advisor regression check ──────────────────────────────────────
    console.print("\n[bold cyan]Step 8/8[/bold cyan] Running Advisor regression check...")
    from retrieval_observatory.advisor.regression import detect_regressions
    from retrieval_observatory.advisor.recommend import recommend, compute_reliability

    await compute_reliability(baseline_run_id, store)
    await compute_reliability(candidate_run_id, store)
    findings = await detect_regressions(baseline_run_id, candidate_run_id, store)
    recs = await recommend(candidate_run_id, store)

    all_fq = await store.get_forge_queries(dataset.dataset_id, limit=500)
    temporal = [q for q in all_fq if q.get("failure_category") == "temporal_confusion"]
    sample_query_id = (
        temporal[0]["query_id"] if temporal else (all_fq[0]["query_id"] if all_fq else "temporal-0-0")
    )

    manifest = {
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_run_id,
        "sample_query_id": sample_query_id,
        "tracelens_service": tracelens_service,
        "forge_dataset_id": dataset.dataset_id,
        "db_path": str(Path(db_path).resolve()),
        "experiment_names": {
            "baseline": "forge-stress-baseline",
            "degraded": "forge-stress-degraded",
        },
    }
    if ablation_run_id:
        manifest["ablation_run_id"] = ablation_run_id
        manifest["experiment_names"]["ablation"] = "forge-stress-ablation"
    manifest_path = out / "demo_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # ── Done ──────────────────────────────────────────────────────────────────
    console.print(f"\n{'─' * 60}")
    console.print(f"[bold green]Demo ready![/bold green] Database: [bold]{db_path}[/bold]")
    console.print("\n[bold]Run IDs[/bold]")
    console.print(f"  Baseline (healthy):  {baseline_run_id}")
    console.print(f"  Degraded (regressed): {candidate_run_id}")
    console.print(f"  Sample query (lineage): {sample_query_id}")

    if findings:
        console.print(f"\n[bold yellow]Advisor regressions detected ({len(findings)}):[/bold yellow]")
        for f in findings[:5]:
            console.print(
                f"  • {f.metric}: {f.before:.3f} → {f.after:.3f} (q={f.q_value:.4f}, {f.severity})"
            )
    else:
        console.print("\n[yellow]Advisor: no significant regressions (unexpected — check query count).[/yellow]")

    if recs:
        console.print(f"\n[bold violet]Top recommendations for degraded run ({len(recs)}):[/bold violet]")
        for i, rec in enumerate(recs[:3], 1):
            console.print(f"  {i}. {rec.action}")

    console.print("\n[bold]Start the dashboard:[/bold]")
    console.print(f"  retobs serve --db {db_path}")
    console.print("  → http://localhost:4000")
    console.print("\n[bold]Explore all four modes:[/bold]")
    console.print("  [bold cyan]Benchmarks[/bold cyan]  Compare baseline vs degraded — stage attribution, failure labels, query explorer")
    console.print("  [bold yellow]Forge[/bold yellow]       #/forge/demo — temporal + alias stress queries, View lineage →")
    console.print(f"  [bold green]TraceLens[/bold green]   #/tracelens/{tracelens_service} — drift (recent vs baseline window), hotspots")
    console.print("  [bold magenta]Advisor[/bold magenta]     #/advisor — recommendations + regression center (runs above)")
    console.print(f"  [dim]Query lineage:[/dim]  #/query/{sample_query_id}")
    console.print("\n[bold]CLI:[/bold]")
    console.print(f"  retobs advisor check --baseline {baseline_run_id} --candidate {candidate_run_id} --db {db_path}")
    console.print(f"  retobs advisor recommend --run {candidate_run_id} --db {db_path}")
    console.print(f"{'─' * 60}\n")


def _demo_config_yaml(
    queries_path: str,
    corpus_path: str,
    db_path: str,
    *,
    k: int = 20,
    experiment_name: str = "forge-stress-demo",
) -> str:
    return f"""\
experiment:
  name: "{experiment_name}"

dataset:
  type: custom
  name: custom
  queries_path: "{queries_path}"
  corpus_path: "{corpus_path}"

stages:
  bm25:
    type: adapter.bm25
    config:
      k: {k}

combinations:
  include:
    - [bm25]

metrics:
  recall_at_k: [5, 10, 20]
  ndcg_at_k: [10]
  mrr: true
  map: true

execution:
  concurrency: 4
  timeout_seconds: 60
  cache_results: false

output:
  store: sqlite
  db_path: "{db_path}"
  export: [json]
"""


def _demo_ablation_config_yaml(queries_path: str, corpus_path: str, db_path: str) -> str:
    return f"""\
experiment:
  name: "forge-stress-ablation"

dataset:
  type: custom
  name: custom
  queries_path: "{queries_path}"
  corpus_path: "{corpus_path}"

stages:
  bm25:
    type: adapter.bm25
    config:
      k: 100
  rerank:
    type: adapter.hf_crossencoder
    config:
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      k: 10

combinations:
  include:
    - [bm25, rerank]
  ablations: true

metrics:
  recall_at_k: [5, 10, 20]
  ndcg_at_k: [10]
  mrr: true
  map: true

execution:
  concurrency: 4
  timeout_seconds: 120
  cache_results: false

output:
  store: sqlite
  db_path: "{db_path}"
  export: [json]
"""


def _demo_corpus_docs() -> list:
    """Synthetic RAG-platform corpus with temporal pairs and alias patterns.

    Temporal pairs: same topic + shared vocabulary, different years → triggers temporal detector.
    Alias groups: 'Full Form (ABBR)' defining doc + standalone-ABBR-only docs → triggers alias detector.
    """
    return [
        # ── Temporal group 1: API Reference ────────────────────────────────
        {
            "id": "api-ref-2021", "timestamp": "2021-03-15T00:00:00",
            "title": "API Reference — Version 1 (2021)",
            "text": (
                "The Version 1 API launched in 2021 provides REST endpoints for search and retrieval. "
                "Authentication uses bearer tokens issued via the OAuth flow. Rate limits in 2021 were "
                "set at 1000 requests per minute for standard plans. The search endpoint accepts query "
                "text and returns ranked results with relevance scores. Pagination uses offset and limit "
                "parameters. Error codes follow HTTP conventions: 401 for unauthorized, 429 for rate "
                "limit exceeded. The 2021 release introduced batch query support for improved throughput. "
                "Token expiry defaults to 8 hours; refresh tokens valid for 30 days."
            ),
        },
        {
            "id": "api-ref-2023", "timestamp": "2023-09-01T00:00:00",
            "title": "API Reference — Version 2 (2023 Update)",
            "text": (
                "The Version 2 API released in 2023 redesigned REST endpoints for improved performance. "
                "Authentication supports API keys in addition to OAuth bearer tokens. Rate limits expanded "
                "in 2023 to 10000 requests per minute for professional plans. The search endpoint supports "
                "semantic filters and hybrid scoring. Pagination uses cursor-based navigation. Error handling "
                "now includes retry-after headers for rate limit responses. New in 2023: streaming responses "
                "and webhook callbacks for async queries. Token refresh flows simplified with PKCE support."
            ),
        },
        # ── Temporal group 2: Subscription Pricing ─────────────────────────
        {
            "id": "pricing-2022", "timestamp": "2022-01-10T00:00:00",
            "title": "Subscription Pricing — 2022",
            "text": (
                "Subscription pricing tiers for 2022: Starter plan costs $29 per month with 10000 monthly "
                "API calls and basic analytics. Professional plan at $99 per month includes 100000 calls, "
                "priority support, and advanced dashboard access. Enterprise subscription requires contacting "
                "sales for custom pricing. All 2022 subscription plans include SSL encryption and 99.9 percent "
                "uptime SLA. Volume discounts apply for annual subscriptions. Monthly billing cycles close on "
                "the first of each month."
            ),
        },
        {
            "id": "pricing-2024", "timestamp": "2024-02-01T00:00:00",
            "title": "Subscription Pricing — 2024 Revision",
            "text": (
                "Updated subscription pricing tiers effective 2024: Starter plan is now $19 per month with "
                "25000 monthly API calls — reduced pricing with expanded limits. Professional plan at $79 per "
                "month includes 250000 monthly calls, semantic search, dedicated support, and custom analytics. "
                "Enterprise subscription in 2024 includes SSO, unlimited calls, and custom SLA negotiation. "
                "All 2024 subscription plans maintain SSL encryption. Annual subscription discounts increased "
                "to 20 percent. New monthly billing dashboards provide cost forecasting."
            ),
        },
        # ── Temporal group 3: Security Guidelines ──────────────────────────
        {
            "id": "security-2022", "timestamp": "2022-06-01T00:00:00",
            "title": "Security Guidelines — 2022",
            "text": (
                "Security guidelines for 2022 mandate encryption of all data in transit using TLS 1.2 or "
                "higher. Access control policies require multi-factor authentication for administrator accounts. "
                "Audit logging captures all read and write operations with timestamp and user identity. "
                "Compliance with SOC 2 Type II required for enterprise customers in 2022. Data encryption at "
                "rest uses AES-256 across all storage tiers. Security incidents must be reported within 24 "
                "hours under the 2022 policy. Penetration testing required quarterly."
            ),
        },
        {
            "id": "security-2024", "timestamp": "2024-04-15T00:00:00",
            "title": "Security Guidelines — 2024 Update",
            "text": (
                "Updated security guidelines for 2024 require TLS 1.3 for all data encryption in transit. "
                "Access control policies now support role-based permissions with granular resource controls. "
                "Audit logging in 2024 includes full query content for compliance investigations. Requirements "
                "expanded to include GDPR and CCPA in addition to SOC 2. Data encryption standards upgraded "
                "across all storage tiers. Security incident reporting threshold reduced to 4 hours under the "
                "2024 policy. Automated penetration testing now runs continuously."
            ),
        },
        # ── Temporal group 4: Release Notes ────────────────────────────────
        {
            "id": "release-notes-2022", "timestamp": "2022-12-01T00:00:00",
            "title": "Release Notes — December 2022",
            "text": (
                "December 2022 release highlights: improved latency for hybrid search queries by 40 percent. "
                "New recall metrics dashboard for monitoring retrieval quality over time. BM25 index rebuild "
                "speed increased 3x. Fixed recall regression introduced in the October 2022 release. "
                "Reranker model updated to improve precision on long-tail queries. Query cache now supports "
                "TTL configuration. Latency p99 reduced from 800ms to 450ms for standard plans. "
                "Deprecation notice: legacy v0 search endpoint removed in this release."
            ),
        },
        {
            "id": "release-notes-2024", "timestamp": "2024-08-01T00:00:00",
            "title": "Release Notes — August 2024",
            "text": (
                "August 2024 release highlights: latency p50 reduced by 25 percent for all search queries "
                "through kernel-level index optimization. Recall@10 improved by 8 percent on long queries. "
                "New reranker model trained on 2024 query logs achieves higher precision on ambiguous queries. "
                "BM25 index now supports incremental updates without full rebuild. Hybrid search latency "
                "improvements benefit all plans. Query cache hit rate monitoring added to the metrics dashboard. "
                "Deprecated: offset-based pagination removed — migrate to cursor-based pagination."
            ),
        },
        # ── Alias group 1: RAG (Retrieval Augmented Generation) ────────────
        {
            "id": "rag-overview", "timestamp": "2023-01-01T00:00:00",
            "title": "Retrieval Augmented Generation Overview",
            "text": (
                "Retrieval Augmented Generation (RAG) is an architecture combining information retrieval "
                "with generative language models. RAG systems first retrieve relevant documents from a "
                "knowledge base, then provide them as context for answer generation. The RAG approach "
                "reduces hallucination by grounding responses in retrieved evidence. Implementing RAG "
                "requires three components: a document corpus, a retrieval engine, and a language model. "
                "RAG pipelines can use sparse retrieval, dense vector search, or hybrid combinations. "
                "Retrieval quality directly impacts generation accuracy in any RAG system."
            ),
        },
        {
            "id": "rag-pipeline-guide", "timestamp": "2023-03-01T00:00:00",
            "title": "RAG Pipeline Configuration Guide",
            "text": (
                "Configuring your RAG pipeline requires careful attention to retrieval parameters. "
                "The query processing stage in a RAG pipeline should normalize text before retrieval. "
                "Chunking strategy significantly impacts RAG performance — shorter chunks improve "
                "precision while longer chunks preserve context. Context window management determines "
                "how many retrieved documents the RAG pipeline passes to the generator. Monitoring "
                "retrieval quality metrics helps identify when your RAG pipeline needs retuning. "
                "Production RAG deployments benefit from caching frequent queries."
            ),
        },
        {
            "id": "rag-evaluation-guide", "timestamp": "2023-05-01T00:00:00",
            "title": "RAG Evaluation Framework",
            "text": (
                "Evaluating a RAG system requires measuring retrieval and generation quality independently. "
                "For the retrieval component of your RAG system, track recall, precision, and ranking "
                "metrics. The generation component of RAG evaluation should assess factual accuracy and "
                "relevance. Human evaluation remains essential for RAG quality assessment since automated "
                "metrics miss nuance. RAG evaluation datasets should include queries across difficulty "
                "levels. Continuous evaluation pipelines ensure RAG quality does not degrade with updates."
            ),
        },
        {
            "id": "rag-limitations", "timestamp": "2023-07-01T00:00:00",
            "title": "RAG Known Limitations and Mitigations",
            "text": (
                "Common limitations of RAG systems include retrieval latency, context window constraints, "
                "and corpus staleness. A RAG system that retrieves irrelevant documents propagates errors "
                "into the generated response. Mitigating RAG latency requires caching, async retrieval, "
                "and index optimization. Context compression techniques help when retrieved documents "
                "exceed the language model context window in a RAG pipeline. Staleness is managed by "
                "scheduling periodic corpus updates and monitoring query drift in your RAG deployment."
            ),
        },
        # ── Alias group 2: RRF (Reciprocal Rank Fusion) ────────────────────
        {
            "id": "rrf-overview", "timestamp": "2023-02-01T00:00:00",
            "title": "Reciprocal Rank Fusion Overview",
            "text": (
                "Reciprocal Rank Fusion (RRF) is a method for combining ranked lists from multiple "
                "retrieval systems. RRF assigns scores using the formula: score = sum of 1/(k + rank_i) "
                "where k is a smoothing constant (typically 60). The RRF approach is robust because it "
                "does not require score normalization across systems. Combining BM25 and dense retrieval "
                "with RRF consistently outperforms either system alone on diverse query sets. "
                "RRF implementation requires only rank positions, not raw scores."
            ),
        },
        {
            "id": "rrf-configuration", "timestamp": "2023-04-01T00:00:00",
            "title": "RRF Configuration Reference",
            "text": (
                "Configuring RRF for your hybrid pipeline involves setting the k parameter and defining "
                "participating retrievers. The k parameter controls how much weight RRF gives to top-ranked "
                "versus lower-ranked results — smaller k emphasizes top results more strongly. For most "
                "production deployments k=60 provides good balance for RRF performance. You can configure "
                "RRF with any number of retrieval systems: sparse, dense, or specialized domain retrievers. "
                "Testing RRF configurations requires evaluation against held-out query sets."
            ),
        },
        {
            "id": "rrf-benchmarks", "timestamp": "2023-06-01T00:00:00",
            "title": "RRF Performance Benchmarks",
            "text": (
                "Benchmark results show RRF consistently improves retrieval quality across diverse query "
                "types. On information-seeking queries, RRF achieves 8 to 15 percent relative improvement "
                "compared to single-system retrieval. For navigational queries, RRF gains are more modest. "
                "RRF excels at tail queries where neither sparse nor dense retrieval alone is reliable. "
                "Latency overhead of RRF is negligible since it only merges pre-retrieved result lists. "
                "Production RRF deployments typically process thousands of merges per second."
            ),
        },
        # ── Alias group 3: ANN (Approximate Nearest Neighbor) ──────────────
        {
            "id": "ann-overview", "timestamp": "2023-01-15T00:00:00",
            "title": "Approximate Nearest Neighbor Search Overview",
            "text": (
                "Approximate Nearest Neighbor (ANN) search finds vectors close to a query vector without "
                "scanning the entire index. ANN algorithms trade exact accuracy for significant speed gains "
                "at scale. Main ANN approaches include HNSW, IVF, and LSH. ANN recall depends on index "
                "parameters: higher recall requires more search effort. Vector databases implement ANN "
                "search at scale with configurable recall targets. ANN performance benchmarks measure "
                "queries per second versus recall tradeoff curves across different index configurations."
            ),
        },
        {
            "id": "ann-index-guide", "timestamp": "2023-03-15T00:00:00",
            "title": "ANN Index Configuration",
            "text": (
                "Building an effective ANN index requires tuning construction parameters for your dataset "
                "size and query latency requirements. The HNSW algorithm provides strong ANN performance "
                "with tunable recall via the ef parameter at search time. For large-scale ANN deployments "
                "with billions of vectors, IVF-based approaches with product quantization reduce memory. "
                "ANN index updates require balancing insertion latency against recall degradation. "
                "Benchmarking your ANN configuration should measure p50, p95, and p99 latency alongside recall."
            ),
        },
        {
            "id": "ann-performance", "timestamp": "2023-05-15T00:00:00",
            "title": "ANN Performance Tuning Guide",
            "text": (
                "Optimizing ANN throughput requires understanding the recall-latency tradeoff for your "
                "workload. The ef_search parameter in HNSW directly controls ANN recall: increasing "
                "ef_search improves recall at the cost of higher query latency. Batching queries "
                "significantly improves ANN throughput on GPU-accelerated indices. Monitoring ANN recall "
                "drift is critical — corpus updates can degrade recall without configuration changes. "
                "ANN index sharding allows horizontal scaling for high-throughput production deployments."
            ),
        },
        # ── Alias group 4: NDCG (Normalized Discounted Cumulative Gain) ────
        {
            "id": "ndcg-guide", "timestamp": "2023-02-15T00:00:00",
            "title": "Normalized Discounted Cumulative Gain Guide",
            "text": (
                "Normalized Discounted Cumulative Gain (NDCG) measures ranking quality by comparing a "
                "system's ranked list against an ideal ranking. NDCG computes a score between 0 and 1 "
                "where 1 indicates perfect ranking. The discounting factor in NDCG reduces the contribution "
                "of relevant documents at lower ranks. NDCG supports graded relevance judgments, making it "
                "more nuanced than binary recall or precision. NDCG@10 and NDCG@100 are the most common "
                "cutoffs in information retrieval benchmarks."
            ),
        },
        {
            "id": "ndcg-evaluation", "timestamp": "2023-04-15T00:00:00",
            "title": "Evaluation Using NDCG Metrics",
            "text": (
                "Reporting NDCG results for retrieval system comparisons requires consistent cutoff values "
                "across experiments. NDCG scores are not directly comparable between datasets with different "
                "relevance grade distributions. When interpreting NDCG improvements, verify statistical "
                "significance using paired tests rather than point estimate differences. A 1-point absolute "
                "improvement in NDCG corresponds to different practical quality gains depending on query "
                "difficulty distribution. Industry benchmarks report NDCG at cutoff 10 for fair comparison."
            ),
        },
        {
            "id": "ndcg-best-practices", "timestamp": "2023-06-15T00:00:00",
            "title": "NDCG Best Practices for RAG Systems",
            "text": (
                "Applying NDCG evaluation to RAG systems requires careful experimental design. NDCG should "
                "be measured on held-out queries not used during system tuning to avoid overfitting to the "
                "evaluation set. For pipelines, report NDCG separately for the retrieval stage and the "
                "end-to-end stage. NDCG variations between runs indicate instability — high NDCG variance "
                "benefits from ensemble approaches. Tracking rolling NDCG averages in production monitoring "
                "is more reliable than point estimates. NDCG regression alerts should trigger on significant drops."
            ),
        },
        # ── General corpus docs ─────────────────────────────────────────────
        {
            "id": "bm25-overview", "timestamp": "2023-01-01T00:00:00",
            "title": "BM25 Lexical Retrieval",
            "text": (
                "BM25 (Best Match 25) is a probabilistic ranking function used in lexical search. It scores "
                "documents based on term frequency and inverse document frequency, with length normalization. "
                "BM25 parameters k1 and b control term saturation and length normalization respectively. "
                "Default values k1=1.5, b=0.75 work well for most corpora. BM25 excels at keyword-matching "
                "queries but struggles with semantic paraphrases. Index building with BM25 is fast and "
                "requires no GPU or neural models. BM25 remains a strong baseline for sparse retrieval."
            ),
        },
        {
            "id": "hybrid-retrieval", "timestamp": "2023-01-01T00:00:00",
            "title": "Hybrid Retrieval: Combining Sparse and Dense",
            "text": (
                "Hybrid retrieval combines lexical search (BM25) with dense vector search to capture both "
                "keyword matches and semantic similarity. The most common combination method is RRF, which "
                "merges ranked lists from each retriever. Alpha-weighted linear interpolation is another "
                "approach that requires score normalization. Hybrid retrieval consistently outperforms "
                "either method alone on benchmark datasets. Latency is approximately the sum of both "
                "retrievers plus a negligible merge cost. Corpus indexing for hybrid systems requires "
                "maintaining both inverted and vector indices in parallel."
            ),
        },
        {
            "id": "reranking-guide", "timestamp": "2023-02-01T00:00:00",
            "title": "Cross-Encoder Reranking Guide",
            "text": (
                "Cross-encoder rerankers jointly encode query and document to produce a fine-grained "
                "relevance score. Unlike bi-encoder models, cross-encoders compute query-document "
                "interactions at inference time, resulting in higher accuracy but more latency. Rerankers "
                "are typically applied to the top-k candidates from a first-stage retriever. Common "
                "reranker models: ms-marco-MiniLM for English, multilingual models for diverse corpora. "
                "Reranker latency scales linearly with k — reranking top-50 is typical for quality "
                "improvement with acceptable latency overhead."
            ),
        },
        {
            "id": "chunking-strategies", "timestamp": "2023-03-01T00:00:00",
            "title": "Document Chunking Strategies for RAG",
            "text": (
                "Chunking divides source documents into segments for indexing in a RAG corpus. Fixed-size "
                "chunks (e.g., 512 tokens) are simple but may split sentences. Sentence-based chunking "
                "preserves semantic units at the cost of variable chunk sizes. Sliding window chunking "
                "with overlap ensures context is not lost at chunk boundaries. Hierarchical chunking "
                "indexes both paragraph and document-level representations. Optimal chunk size depends "
                "on query type: short chunks work for factual queries, longer chunks for synthesis tasks."
            ),
        },
        {
            "id": "evaluation-metrics", "timestamp": "2023-03-15T00:00:00",
            "title": "Retrieval Evaluation Metrics Overview",
            "text": (
                "Key metrics for retrieval evaluation: Recall@K measures the fraction of relevant documents "
                "retrieved in the top-K results. Precision@K measures the fraction of top-K results that "
                "are relevant. MRR (Mean Reciprocal Rank) focuses on the rank of the first relevant result. "
                "MAP (Mean Average Precision) averages precision across all recall levels. NDCG accounts "
                "for graded relevance and rank position. For RAG systems, end-to-end generation quality "
                "metrics like faithfulness and answer relevance complement retrieval metrics."
            ),
        },
        {
            "id": "query-expansion", "timestamp": "2023-04-01T00:00:00",
            "title": "Query Expansion Techniques",
            "text": (
                "Query expansion adds terms to the original query to improve recall for under-specified "
                "queries. Pseudo-relevance feedback expands using terms from top retrieved documents. "
                "Synonym expansion uses a thesaurus or word embeddings to add related terms. LLM-based "
                "expansion generates hypothetical documents that improve dense retrieval recall. "
                "Query expansion improves recall but can hurt precision if expansion terms are noisy. "
                "Expansion is most effective for short, ambiguous queries in specialized domains."
            ),
        },
        {
            "id": "production-monitoring", "timestamp": "2023-05-01T00:00:00",
            "title": "Production Retrieval Monitoring",
            "text": (
                "Monitoring production retrieval systems requires tracking both technical and quality metrics. "
                "Technical metrics include query latency (p50, p95, p99), error rates, and index freshness. "
                "Quality signals without labels include empty result rates, low-score result rates, and "
                "query abandonment rates. Drift detection compares current query distributions against "
                "a baseline window to identify distribution shifts. Alerting on suspected retrieval failures "
                "enables proactive quality management before users report problems."
            ),
        },
        {
            "id": "embedding-models", "timestamp": "2023-06-01T00:00:00",
            "title": "Embedding Model Selection Guide",
            "text": (
                "Selecting an embedding model for dense retrieval requires balancing accuracy, latency, "
                "and cost. Bi-encoder models like sentence-transformers encode query and document separately "
                "for efficient retrieval. Larger embedding dimensions generally improve retrieval quality "
                "at the cost of increased index storage and search latency. Domain-specific fine-tuning "
                "significantly improves retrieval quality over general-purpose models for specialized corpora. "
                "Benchmarking embedding models on BEIR datasets provides a standardized quality comparison."
            ),
        },
        {
            "id": "index-optimization", "timestamp": "2023-07-01T00:00:00",
            "title": "Index Optimization Best Practices",
            "text": (
                "Optimizing retrieval indices reduces query latency and infrastructure costs. For BM25, "
                "disable storing term positions if phrase queries are not required. Quantizing dense "
                "vectors to int8 reduces memory 4x with minimal recall loss. Partitioning large indices "
                "by document metadata enables faster filtered queries. Warm-up queries after index load "
                "prevent cold-start latency spikes in production. Monitoring index staleness ensures "
                "retrieval quality does not degrade as the corpus evolves over time."
            ),
        },
        {
            "id": "cost-optimization", "timestamp": "2023-08-01T00:00:00",
            "title": "Cost Optimization for Retrieval Systems",
            "text": (
                "Cost optimization in retrieval systems targets compute, storage, and API spend. Caching "
                "frequent queries eliminates redundant retrieval computation — cache hit rates above 20 "
                "percent significantly reduce costs. Quantized dense indices reduce storage and accelerate "
                "search. Smaller reranker models (e.g., 6-layer cross-encoders) offer 80 percent of the "
                "quality at 30 percent of the latency and cost. Batching embedding requests reduces API "
                "costs for cloud-hosted models. Right-sizing replicas based on p99 latency requirements "
                "avoids over-provisioning."
            ),
        },
        {
            "id": "vector-databases", "timestamp": "2023-09-01T00:00:00",
            "title": "Vector Database Comparison",
            "text": (
                "Vector databases store dense embeddings and support approximate nearest neighbor search "
                "at scale. Key players: Pinecone (managed, serverless option), Weaviate (open-source, "
                "multimodal), Qdrant (high-performance, Rust-based), Chroma (lightweight, local-first). "
                "Selection criteria: scale requirements, filtering capabilities, update frequency, "
                "managed vs self-hosted preference, and cost. Most vector databases support metadata "
                "filtering alongside vector similarity search. Integration with embedding APIs is "
                "straightforward for all major vector database providers."
            ),
        },
        {
            "id": "metadata-filtering", "timestamp": "2023-10-01T00:00:00",
            "title": "Metadata Filtering in Retrieval",
            "text": (
                "Metadata filtering restricts retrieval to documents matching attribute constraints "
                "before or after vector search. Pre-filtering reduces the candidate set before ANN "
                "search — effective for high-cardinality filters but degrades recall on small post-filter "
                "sets. Post-filtering retrieves broadly then removes non-matching documents — safer for "
                "recall but requires over-retrieval. Hybrid approaches use the filter to guide index "
                "partitioning. Common filter attributes: document date, source, language, category, "
                "and access permissions. Indexed metadata dramatically reduces filter evaluation cost."
            ),
        },
        {
            "id": "latency-optimization", "timestamp": "2023-11-01T00:00:00",
            "title": "Retrieval Latency Optimization",
            "text": (
                "Reducing retrieval latency requires profiling the full request path: query encoding, "
                "index search, reranking, and result serialization. Async execution of independent stages "
                "cuts wall-clock time for multi-stage pipelines. Early termination in ANN search stops "
                "exploration once enough high-confidence candidates are found. Speculative prefetching "
                "warms the reranker cache for likely follow-up queries. Hardware acceleration with GPU "
                "reduces dense retrieval latency 5-10x. Target p99 latency as the optimization criterion "
                "rather than average latency to improve worst-case user experience."
            ),
        },
        {
            "id": "dataset-preparation", "timestamp": "2023-12-01T00:00:00",
            "title": "Evaluation Dataset Preparation",
            "text": (
                "Preparing a high-quality evaluation dataset is the most critical step in retrieval "
                "benchmarking. Queries should represent realistic user intent distributions, not just "
                "easy factual lookups. Relevance judgments require either human annotators or LLM-based "
                "grading with validation. Include hard negatives — documents topically similar to relevant "
                "ones but not actually relevant — to stress-test ranking quality. Dataset splits must "
                "avoid query-document leakage between train and test. Minimum dataset size for reliable "
                "metric estimation: 100 queries for point estimates, 500 for significance testing."
            ),
        },
        {
            "id": "sparse-vs-dense", "timestamp": "2024-01-01T00:00:00",
            "title": "Sparse vs Dense Retrieval Tradeoffs",
            "text": (
                "Sparse retrieval (BM25, SPLADE) matches on exact term overlap — fast, interpretable, "
                "and effective for keyword-heavy queries. Dense retrieval (bi-encoders) captures semantic "
                "similarity even without term overlap — better for paraphrase and synonym queries. "
                "Sparse methods have zero cold-start latency and require no GPU. Dense methods require "
                "embedding all corpus documents upfront and maintaining a vector index. In practice, "
                "hybrid pipelines combining sparse and dense retrieval outperform either alone on "
                "most diverse real-world query distributions."
            ),
        },
        {
            "id": "recall-at-k-guide", "timestamp": "2024-02-01T00:00:00",
            "title": "Recall@K Interpretation Guide",
            "text": (
                "Recall@K measures what fraction of all relevant documents for a query appear in the "
                "top-K results. For RAG systems, Recall@10 is typically the target since language models "
                "process 5-10 retrieved documents. Recall@100 measures first-stage retriever coverage "
                "before reranking. Recall is bounded by the depth of relevance judgments — incomplete "
                "annotation inflates apparent recall. When comparing systems, always use the same K and "
                "the same qrel depth. Statistical significance for recall differences requires at least "
                "50 queries; bootstrap confidence intervals quantify uncertainty."
            ),
        },
    ]


def _build_demo_queries(
    scenarios: list,
    corpus_dict: dict,
) -> tuple:
    """Create hand-crafted synthetic queries matched to detected Forge scenarios.

    Each query gets scenario_type and difficulty_label in its metadata so the
    by-segment endpoint can power the StressTestResults cross-link in the dashboard.
    """
    from retrieval_observatory.forge.types import SyntheticQuery
    import re as _re

    queries: list = []
    qrels: dict = {}

    temporal_scenarios = [s for s in scenarios if s.scenario_type == "temporal"]
    alias_scenarios = [s for s in scenarios if s.scenario_type == "alias"]

    # ── Temporal query templates ────────────────────────────────────────────
    # These are designed so the query text is ambiguous between the old and new
    # version of the same topic — exactly the retrieval failure pattern.
    _TEMPORAL_TEMPLATES = [
        ("What is the current {topic}?", "temporal", "hard"),
        ("Show me the latest {topic} documentation.", "temporal", "hard"),
        ("How has {topic} changed over time?", "paraphrase", "medium"),
        ("What were the {topic} guidelines in the earlier version?", "paraphrase", "easy"),
        ("Updated {topic} policy and terms.", "temporal", "extreme"),
    ]

    for i, scenario in enumerate(temporal_scenarios[:5]):
        anchor_ids = list(scenario.anchor_doc_ids)
        if not anchor_ids:
            continue
        # Derive a topic label from the first anchor doc's title
        first_doc = corpus_dict.get(anchor_ids[0], {})
        title = first_doc.get("title", "")
        # Strip years, trailing version/update qualifiers, and empty parentheses
        topic = _re.sub(r"\b(19|20)\d{2}\b", "", title)
        topic = _re.sub(r"\b(version|update|revision|release|v\d+)\b.*", "", topic, flags=_re.IGNORECASE)
        topic = _re.sub(r"\(\s*\)", "", topic)
        topic = topic.strip(" —-–|").lower()
        topic = _re.sub(r"\s+", " ", topic).strip()
        if not topic:
            topic = "retrieval configuration"

        for tmpl, qtype, difficulty in _TEMPORAL_TEMPLATES:
            q_text = tmpl.format(topic=topic)
            q_id = f"temporal-{i}-{len(queries)}"
            queries.append(SyntheticQuery(
                query_id=q_id,
                text=q_text,
                scenario_id=scenario.scenario_id,
                query_type=qtype,
                positive_doc_ids=anchor_ids,
                difficulty_label=difficulty,
                failure_category="temporal_confusion",
                validated=False,
                metadata={"scenario_type": "temporal"},
            ))
            qrels[q_id] = {doc_id: 2 for doc_id in anchor_ids}

    # ── Alias query templates ───────────────────────────────────────────────
    # Queries use the abbreviation only — the relevant doc uses the full form.
    _ALIAS_TEMPLATES = [
        ("How does {abbr} work and when should I use it?", "paraphrase", "hard"),
        ("Configure {abbr} for my retrieval pipeline.", "paraphrase", "hard"),
        ("What are the performance characteristics of {abbr}?", "paraphrase", "medium"),
        ("Best practices for {abbr} in production deployments.", "adversarial", "extreme"),
        ("{abbr} vs alternative approaches — comparison.", "adversarial", "hard"),
    ]

    for i, scenario in enumerate(alias_scenarios[:5]):
        anchor_ids = list(scenario.anchor_doc_ids)
        if not anchor_ids:
            continue
        # Extract abbreviation from evidence summary (pattern: "abbreviation: ABBR")
        abbr_match = _re.search(r"abbreviation[:\s]+([A-Z]{2,6})", scenario.evidence_summary, _re.IGNORECASE)
        if not abbr_match:
            # Fallback: look for uppercase acronym
            abbr_match = _re.search(r"\b([A-Z]{2,6})\b", scenario.evidence_summary)
        abbr = abbr_match.group(1).upper() if abbr_match else "ABBR"

        for tmpl, qtype, difficulty in _ALIAS_TEMPLATES:
            q_text = tmpl.format(abbr=abbr)
            q_id = f"alias-{i}-{len(queries)}"
            queries.append(SyntheticQuery(
                query_id=q_id,
                text=q_text,
                scenario_id=scenario.scenario_id,
                query_type=qtype,
                positive_doc_ids=anchor_ids,
                difficulty_label=difficulty,
                failure_category="alias_mismatch",
                validated=False,
                metadata={"scenario_type": "alias"},
            ))
            qrels[q_id] = {doc_id: 2 for doc_id in anchor_ids}

    # ── General easy queries (balanced difficulty distribution) ─────────────
    _GENERAL_QUERIES: list = [
        ("What is BM25 retrieval and how does it score documents?",
         ["bm25-overview"], "easy", "paraphrase"),
        ("How do I combine BM25 and vector search in a hybrid pipeline?",
         ["hybrid-retrieval", "rrf-overview"], "easy", "paraphrase"),
        ("When should I use a cross-encoder reranker?",
         ["reranking-guide"], "easy", "paraphrase"),
        ("What document chunking strategy is best for question answering?",
         ["chunking-strategies"], "easy", "paraphrase"),
        ("How do I interpret Recall@10 for my retrieval system?",
         ["recall-at-k-guide", "evaluation-metrics"], "medium", "paraphrase"),
        ("What is the difference between sparse and dense retrieval?",
         ["sparse-vs-dense", "bm25-overview", "ann-overview"], "medium", "paraphrase"),
        ("How do I reduce query latency in production?",
         ["latency-optimization", "index-optimization"], "medium", "paraphrase"),
        ("Which vector database should I choose?",
         ["vector-databases"], "easy", "paraphrase"),
        ("How do I filter search results by metadata?",
         ["metadata-filtering"], "easy", "paraphrase"),
        ("How do I build an evaluation dataset for my retrieval system?",
         ["dataset-preparation"], "medium", "paraphrase"),
        ("What metrics should I track to monitor retrieval quality in production?",
         ["production-monitoring", "evaluation-metrics"], "hard", "adversarial"),
        ("How do embedding model choices affect RAG system accuracy?",
         ["embedding-models", "rag-overview"], "medium", "paraphrase"),
    ]

    for q_text, pos_ids, difficulty, qtype in _GENERAL_QUERIES:
        # Filter to only doc IDs that exist in corpus
        valid_pos = [d for d in pos_ids if d in corpus_dict]
        if not valid_pos:
            continue
        q_id = f"general-{len(queries)}"
        # Use the first detected scenario of either type, or a dummy id
        scene_id = scenarios[0].scenario_id if scenarios else "general"
        queries.append(SyntheticQuery(
            query_id=q_id,
            text=q_text,
            scenario_id=scene_id,
            query_type=qtype,
            positive_doc_ids=valid_pos,
            difficulty_label=difficulty,
            failure_category=None,
            validated=False,
            metadata={"scenario_type": "general"},
        ))
        qrels[q_id] = {doc_id: 2 for doc_id in valid_pos}

    return queries, qrels


def _append_demo_forge_tags(trace) -> None:
    """Add Forge failure_category tags so query lineage prod-matches work in the demo."""
    text = trace.query_text.lower()
    tags = list(trace.suspected_failures or [])
    temporal_markers = ("2022", "2023", "2024", "current", "latest", "earlier version", "changed over time", "versus")
    alias_markers = ("aws vs", "amazon web services", " rrf ", " rag ", " bm25 ", " ann ")
    if any(m in text for m in temporal_markers) and "temporal_confusion" not in tags:
        tags.append("temporal_confusion")
        trace.predicted_difficulty = "hard"
    if any(m in text for m in alias_markers) and "alias_mismatch" not in tags:
        tags.append("alias_mismatch")
        trace.predicted_difficulty = "hard"
    trace.suspected_failures = tags


async def _seed_showcase_traces(service: str, n: int, db_path: str) -> None:
    """Seed production traces designed for drift, hotspots, and lineage categorical matches."""
    import random
    import uuid
    from datetime import datetime, timedelta, timezone

    from retrieval_observatory.store.sqlite import SQLiteStore
    from retrieval_observatory.tracing.enrich import enrich
    from retrieval_observatory.tracing.types import RetrievalTrace
    from retrieval_observatory.types import Document, StageSnapshot

    store = SQLiteStore(db_path=db_path)
    await store.init_db()

    random.seed(42)
    now = datetime.now(timezone.utc)

    healthy_queries = [
        "what is the refund policy",
        "how do I reset my password",
        "explain the onboarding flow step by step",
    ]
    temporal_queries = [
        "compare the 2022 and 2024 pricing tiers",
        "what is the current api reference documentation",
        "show me the latest security guidelines",
        "how has subscription pricing changed over time",
        "what were the security guidelines in the earlier version",
    ]
    alias_queries = [
        "AWS vs Amazon Web Services billing differences",
        "how does RAG work and when should I use it",
        "configure RRF for my hybrid retrieval pipeline",
        "BM25 vs alternative approaches comparison",
    ]
    hard_queries = [
        "why was my account suspended and how do I appeal the decision",
        "did the API change after the 2023 migration versus the legacy endpoint",
    ]

    pipelines = ["bm25", "hybrid", "hybrid__rerank"]
    traces: list = []

    def _docs(count: int, score_lo: float = 0.4, score_hi: float = 0.95) -> list:
        return [
            Document(id=f"d{j}", text="doc", score=random.uniform(score_lo, score_hi), rank=j + 1)
            for j in range(count)
        ]

    for i in range(n):
        recent_window = i >= int(n * 0.55)
        if recent_window:
            ts = now - timedelta(hours=random.randint(1, 72))
            failure_roll = random.random()
        else:
            ts = now - timedelta(days=random.uniform(9, 14), hours=random.randint(0, 12))
            failure_roll = random.random() * 0.35

        if failure_roll < 0.12:
            q = random.choice(temporal_queries + hard_queries)
            pipeline = random.choice(pipelines)
            snapshots = [StageSnapshot(0, "bm25", [], random.uniform(15, 80), candidate_count=0)]
            final: list = []
            latency = snapshots[0].latency_ms
            status = "OK"
        elif failure_roll < 0.22:
            q = random.choice(hard_queries + temporal_queries)
            pipeline = "hybrid__rerank"
            docs = _docs(10)
            snapshots = [
                StageSnapshot(0, "bm25", docs, random.uniform(40, 120), candidate_count=10),
                StageSnapshot(1, "rerank", _docs(1, 0.1, 0.2), random.uniform(2500, 4500), candidate_count=1),
            ]
            final = snapshots[1].documents
            latency = sum(s.latency_ms for s in snapshots)
            status = "OK"
        elif failure_roll < 0.32 and recent_window:
            q = random.choice(alias_queries)
            pipeline = "hybrid__rerank"
            docs = _docs(10)
            kept = docs[:2]
            snapshots = [
                StageSnapshot(0, "bm25", docs, random.uniform(30, 90), candidate_count=10),
                StageSnapshot(1, "rerank", kept, random.uniform(50, 150), candidate_count=2),
            ]
            final = kept
            latency = sum(s.latency_ms for s in snapshots)
            status = "OK"
        else:
            q = random.choice(healthy_queries + alias_queries[:1])
            pipeline = random.choice(pipelines)
            docs = _docs(8, 0.6, 0.98)
            snapshots = [StageSnapshot(0, "bm25", docs, random.uniform(15, 60), candidate_count=8)]
            if "rerank" in pipeline:
                kept = docs[:5]
                snapshots.append(
                    StageSnapshot(1, "rerank", kept, random.uniform(25, 70), candidate_count=5)
                )
                final = kept
            else:
                final = docs[:5]
            latency = sum(s.latency_ms for s in snapshots)
            status = "OK"

        trace = RetrievalTrace(
            trace_id=uuid.uuid4().hex,
            service=service,
            query_id=uuid.uuid4().hex[:8],
            query_text=q,
            pipeline_id=pipeline,
            snapshots=snapshots,
            total_latency_ms=latency,
            status=status,
            timestamp=ts,
            final_results=final,
        )
        enrich(trace, latency_budget_ms=800.0)
        _append_demo_forge_tags(trace)
        traces.append(trace)

    await store.save_traces_batch(traces)
    console.print(
        f"  [green]✓[/green] {len(traces)} traces — "
        f"~{int(n * 0.45)} baseline-window (healthy) + ~{int(n * 0.55)} recent (elevated failures for drift)"
    )


@tracelens_app.command("demo")
def tracelens_demo(
    service: str = typer.Option("demo", "--service", help="Service name to attach the synthetic traces to."),
    n: int = typer.Option(200, "--n", help="Number of synthetic traces to seed."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="Store DB to write traces into."),
) -> None:
    """Seed synthetic production traces so the TraceLens dashboard has data to explore."""
    asyncio.run(_tracelens_demo(service, n, db))


async def _tracelens_demo(service: str, n: int, db_path: str) -> None:
    await _seed_showcase_traces(service, n, db_path)
    console.print("[dim]Open the dashboard (retobs serve) → TraceLens mode to explore them.[/dim]")


@tracelens_app.command("stats")
def tracelens_stats(
    service: str = typer.Option(..., "--service", help="Service name to summarize."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="Store DB to read from."),
) -> None:
    """Print a summary of stored traces for a service (count, error rate, latency, suspected failures)."""
    asyncio.run(_tracelens_stats(service, db))


async def _tracelens_stats(service: str, db_path: str) -> None:
    from retrieval_observatory.store.sqlite import SQLiteStore
    from retrieval_observatory.tracing.monitor.distribution import summarize, compute_distribution

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    rows = await store.list_traces(service, limit=1_000_000)
    if not rows:
        console.print(f"[yellow]No traces found for service '{service}'.[/yellow]")
        return
    s = summarize(rows)
    dist = compute_distribution(rows)

    table = Table(title=f"TraceLens — {service}", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Traces", str(s["trace_count"]))
    table.add_row("OK rate", f"{s['ok_rate'] * 100:.1f}%")
    table.add_row("Error rate", f"{s['error_rate'] * 100:.1f}%")
    table.add_row("Latency p50", f"{s['latency_p50']:.0f} ms")
    table.add_row("Latency p95", f"{s['latency_p95']:.0f} ms")
    table.add_row("Suspected-failure rate", f"{s['suspected_failure_rate'] * 100:.1f}%")
    console.print(table)

    if dist["by_failure_label"]:
        console.print("[dim]Suspected failures are label-free proxy signals, not measured Recall.[/dim]")
        ftable = Table(title="Suspected failure signals", show_header=True)
        ftable.add_column("Signal", style="cyan")
        ftable.add_column("Count", style="bold")
        for label, count in sorted(dist["by_failure_label"].items(), key=lambda x: -x[1]):
            ftable.add_row(label, str(count))
        console.print(ftable)


@tracelens_app.command("purge")
def tracelens_purge(
    service: str = typer.Option(..., "--service", help="Service whose traces to purge."),
    older_than_days: Optional[int] = typer.Option(None, "--older-than-days", help="Only purge traces older than N days."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="Store DB to purge from."),
) -> None:
    """Delete stored traces for a service (optionally only those older than N days)."""
    asyncio.run(_tracelens_purge(service, older_than_days, db))


async def _tracelens_purge(service: str, older_than_days: Optional[int], db_path: str) -> None:
    from datetime import datetime, timedelta, timezone
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    cutoff = None
    if older_than_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    deleted = await store.purge_traces(service=service, older_than=cutoff)
    console.print(f"[green]Purged {deleted} traces[/green] for service '{service}'.")


def _open_store(db_path: str):
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    return store


@advisor_app.command("check")
def advisor_check(
    baseline: str = typer.Option(..., "--baseline", help="Baseline run ID."),
    candidate: str = typer.Option(..., "--candidate", help="Candidate run ID."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
) -> None:
    """Compare two runs and exit non-zero if significant regressions are found."""
    asyncio.run(_advisor_check(baseline, candidate, db))


async def _advisor_check(baseline: str, candidate: str, db_path: str) -> None:
    from retrieval_observatory.advisor.regression import detect_regressions

    store = _open_store(db_path)
    await store.init_db()
    findings = await detect_regressions(baseline, candidate, store)
    if not findings:
        console.print("[green]No significant regressions detected.[/green]")
        return
    table = Table(title="Regressions")
    table.add_column("Metric")
    table.add_column("Before")
    table.add_column("After")
    table.add_column("Delta")
    table.add_column("q-value")
    table.add_column("Severity")
    table.add_column("n pairs")
    for f in findings:
        table.add_row(
            f.metric,
            f"{f.before:.4f}",
            f"{f.after:.4f}",
            f"{f.delta:+.4f}",
            f"{f.q_value:.4f}",
            f.severity,
            str(f.n_pairs),
        )
    console.print(table)
    raise typer.Exit(1)


@advisor_app.command("recommend")
def advisor_recommend_cmd(
    run_id: str = typer.Option(..., "--run", help="Run ID to analyze."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
) -> None:
    """Print ranked, evidence-cited recommendations for a run."""
    asyncio.run(_advisor_recommend(run_id, db))


async def _advisor_recommend(run_id: str, db_path: str) -> None:
    from retrieval_observatory.advisor.recommend import recommend

    store = _open_store(db_path)
    await store.init_db()
    recs = await recommend(run_id, store)
    if not recs:
        console.print("[green]No recommendations — diagnostics look healthy.[/green]")
        return
    for i, rec in enumerate(recs, 1):
        console.print(f"\n[bold]{i}. {rec.action}[/bold]")
        console.print(f"   {rec.rationale}")
        for ev in rec.evidence:
            console.print(f"   • {ev}")


golden_app = typer.Typer(name="golden", help="Golden set management.")
advisor_app.add_typer(golden_app, name="golden")


@golden_app.command("run")
def golden_run(
    set_name: str = typer.Option(..., "--set", help="Golden set name."),
    config: Path = typer.Option(..., "--config", "-c", help="Experiment YAML config."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
) -> None:
    """Run a golden benchmark tagged with the given set name."""
    asyncio.run(_golden_run(set_name, config, db))


async def _golden_run(set_name: str, config_path: Path, db_path: str) -> None:
    store = _open_store(db_path)
    await store.init_db()
    existing = await store.get_golden_set(set_name)
    if not existing:
        console.print(f"[red]Golden set '{set_name}' not found. Create it first.[/red]")
        raise typer.Exit(1)
    await _run(config_path, skip_smoke_test=False, no_cache=False, golden_set=set_name)


@golden_app.command("list")
def golden_list(
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
) -> None:
    """List registered golden sets."""
    asyncio.run(_golden_list(db))


async def _golden_list(db_path: str) -> None:
    store = _open_store(db_path)
    await store.init_db()
    sets = await store.list_golden_sets()
    if not sets:
        console.print("No golden sets registered.")
        return
    table = Table(title="Golden Sets")
    table.add_column("Name")
    table.add_column("Created")
    for row in sets:
        table.add_row(row["name"], row.get("created_at", ""))
    console.print(table)


@golden_app.command("create")
def golden_create(
    set_name: str = typer.Option(..., "--set", help="Golden set name."),
    queries_file: Path = typer.Option(..., "--queries", help="JSON file: list of {query_id, text, relevant_doc_ids}."),
    db: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
) -> None:
    """Register a golden set from a JSON queries file."""
    asyncio.run(_golden_create(set_name, queries_file, db))


async def _golden_create(set_name: str, queries_file: Path, db_path: str) -> None:
    from retrieval_observatory.advisor.golden import save_golden_set

    data = json.loads(queries_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        console.print("[red]Queries file must be a JSON list.[/red]")
        raise typer.Exit(1)
    store = _open_store(db_path)
    await store.init_db()
    await save_golden_set(store, set_name, data)
    console.print(f"[green]Registered golden set '{set_name}' ({len(data)} queries).[/green]")


@app.command()
def quickstart(
    output_dir: Path = typer.Option(Path(".retobs/quickstart"), "--output-dir", "-o", help="Directory for all quickstart outputs."),
    db: str = typer.Option(".retobs/quickstart/results.db", "--db", "--db-path", help="SQLite DB to write results into."),
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(4000, "--port"),
) -> None:
    """Cold-start: corpus → Forge scan → BM25 benchmark → TraceLens traces → dashboard.

    No API keys or external services required.  Takes under 5 minutes from a
    fresh install.  After completion, open the URL printed below to explore
    benchmark results and per-query failure labels in the TraceLens tab.

    Minimum install: pip install retrieval-observatory[demo,dashboard]
    """
    asyncio.run(_quickstart(output_dir=str(output_dir), db_path=db, host=host, port=port))


async def _quickstart(output_dir: str, db_path: str, host: str, port: int) -> None:
    import time

    try:
        import uvicorn
        from retrieval_observatory.dashboard.api import create_app
        from retrieval_observatory.dashboard.registry import DbRegistry
    except ImportError:
        console.print("[red]Dashboard requires fastapi+uvicorn. Run: pip install retrieval-observatory[dashboard][/red]")
        raise typer.Exit(1)

    console.print("[bold green]retobs quickstart[/bold green] — building demo in [dim]~30 seconds[/dim] …\n")
    t0 = time.monotonic()

    # Delegate to the demo builder (fast mode: small n_traces, no full ablation)
    await _demo(
        output_dir=output_dir,
        db_path=db_path,
        tracelens_service="quickstart",
        n_traces=50,
        keep_db=False,
        full=False,
    )

    elapsed = time.monotonic() - t0
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    console.print(f"\n[bold green]✓ Ready in {elapsed:.0f}s[/bold green]")
    console.print(f"  Benchmarks  → http://{display_host}:{port}")
    console.print(f"  TraceLens   → http://{display_host}:{port}/tracelens")
    console.print(f"  Advisor     → http://{display_host}:{port}/advisor")
    console.print(
        "\n  [dim]What you're seeing: Forge found retrieval failure scenarios in a synthetic\n"
        "  RAG corpus, built stress-test queries, ran a BM25 benchmark against them,\n"
        "  and seeded TraceLens with 50 production-shaped traces with failure labels.\n"
        "  Open the TraceLens tab and look at 'suspected_failures' per query.[/dim]\n"
    )

    registry = DbRegistry([db_path])
    dashboard_app = create_app(registry=registry)
    # uvicorn.run() calls asyncio.run() internally; we are already inside
    # asyncio.run(_quickstart(...)), so start the server on the active loop.
    config = uvicorn.Config(dashboard_app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    app()
