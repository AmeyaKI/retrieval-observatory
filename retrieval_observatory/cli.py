from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="retobs",
    help="Local-first retrieval reliability: evaluate, compare, debug, and investigate RAG retrieval.",
    no_args_is_help=True,
)
mcp_app = typer.Typer(name="mcp", help="Run the MCP server and bootstrap agent integration.")
storage_app = typer.Typer(name="storage", help="Migrate the results database schema and index runs for investigation.")
app.add_typer(mcp_app, name="mcp")
app.add_typer(storage_app, name="storage")
console = Console()


def _load_evaluate_target(spec: str):
    """Load module:symbol or /path/file.py:symbol without mutating project files."""
    import importlib
    import importlib.util
    import sys

    if ":" not in spec:
        raise ValueError("Callable target must use module:symbol or /path/file.py:symbol.")
    module_ref, symbol = spec.rsplit(":", 1)
    path = Path(module_ref)
    if path.suffix == ".py" or path.exists():
        resolved = path.resolve()
        # The file's own package imports (``from app.searcher import ...``) resolve against its
        # directory and the project root the command runs from; leave both on sys.path because
        # the loaded module may import lazily during evaluation.
        for entry in (str(Path.cwd()), str(resolved.parent)):
            if entry not in sys.path:
                sys.path.insert(0, entry)
        module_spec = importlib.util.spec_from_file_location(f"retobs_user_{resolved.stem}", resolved)
        if module_spec is None or module_spec.loader is None:
            raise ValueError(f"Cannot import Python file: {resolved}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        project_root = str(Path.cwd())
        added_project_root = project_root not in sys.path
        if added_project_root:
            sys.path.insert(0, project_root)
        try:
            module = importlib.import_module(module_ref)
        finally:
            if added_project_root:
                sys.path.remove(project_root)
    if not hasattr(module, symbol):
        raise ValueError(f"Symbol '{symbol}' not found in {module_ref}.")
    return getattr(module, symbol), module


def _read_json_records(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    # A one-line JSONL file parses as a single object; a row (query or judgment) is still one record.
    if isinstance(parsed, dict) and ("query_id" in parsed or "doc_id" in parsed):
        return [parsed]
    return parsed


def _evaluate_inputs(module, queries_path: Optional[Path], corpus_path: Optional[Path], qrels_path: Optional[Path]):
    queries = _read_json_records(queries_path) if queries_path else getattr(module, "QUERIES", getattr(module, "queries", None))
    corpus_raw = _read_json_records(corpus_path) if corpus_path else getattr(module, "CORPUS", getattr(module, "corpus", None))
    qrels_raw = _read_json_records(qrels_path) if qrels_path else getattr(module, "QRELS", getattr(module, "qrels", None))
    if isinstance(corpus_raw, list):
        corpus = {
            str(row.get("id", row.get("doc_id"))): str(row.get("text", row.get("content", "")))
            for row in corpus_raw
        }
    else:
        corpus = corpus_raw
    if isinstance(qrels_raw, list):
        qrels = {}
        for row in qrels_raw:
            if not (isinstance(row, dict) and row.get("query_id")):
                continue
            if "doc_id" in row:  # one judged pair per row: {query_id, doc_id, relevance}
                graded = qrels.setdefault(str(row["query_id"]), {})
                if isinstance(graded, dict):
                    graded[str(row["doc_id"])] = int(row.get("relevance", 1))
            else:
                qrels[str(row["query_id"])] = row.get("relevant_doc_ids", row.get("qrels", {}))
    else:
        qrels = qrels_raw
    if not queries or not corpus:
        raise ValueError(
            "Evaluation needs queries and corpus. Pass --queries/--corpus JSON(L), "
            "or define QUERIES and CORPUS in the target module."
        )
    return queries, corpus, qrels


def _read_chunk_map(path: Path):
    return [
        (str(row["chunk_id"]), str(row["document_id"]), *([str(row["namespace"])] if row.get("namespace") else []))
        for row in _read_json_records(path)
    ]


@app.command("evaluate")
def evaluate_cmd(
    target: Optional[str] = typer.Argument(None, help="Python callable as module:symbol or /path/file.py:symbol."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Advanced YAML evaluation config."),
    queries: Optional[Path] = typer.Option(None, "--queries", help="Query JSON/JSONL; optional when module defines QUERIES."),
    corpus: Optional[Path] = typer.Option(None, "--corpus", help="Corpus JSON/JSONL; optional when module defines CORPUS."),
    qrels: Optional[Path] = typer.Option(None, "--qrels", help="Qrel JSON/JSONL; optional when queries embed relevant_doc_ids."),
    k: int = typer.Option(10, "--k", min=1, help="Evaluation cutoff."),
    name: Optional[str] = typer.Option(None, "--name", help="Run/pipeline display name."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite result database; config output is used when omitted."),
    max_queries: Optional[int] = typer.Option(None, "--max-queries", min=1, help="Bound the query sample."),
    format: str = typer.Option("terminal", "--format", help="terminal|json|markdown|html"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write the report artifact."),
    provenance: List[str] = typer.Option(
        [], "--provenance", help="Release identity KEY=VALUE (repeatable): service_id, deployment_revision, corpus_revision, index_build_id, chunking_revision, embedding_model_revision, reranker_model_revision."
    ),
    chunk_map: Optional[Path] = typer.Option(None, "--chunk-map", help="JSONL rows {chunk_id, document_id, namespace?} mapping chunk results to judged documents."),
) -> None:
    """Evaluate a Python retrieval callable, or an advanced YAML config with --config."""
    import rich

    import retrieval_observatory as ro
    from retrieval_observatory.sdk import run_from_config

    # The benchmark runner's progress bar renders on rich's global console; keep it off stdout so
    # `--format json` output stays parseable when piped.
    rich.reconfigure(stderr=True)
    try:
        if bool(target) == bool(config):
            raise ValueError("Provide exactly one callable target or --config <yaml>.")
        if config:
            import yaml

            payload = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            report = run_from_config(
                payload,
                db_path=db,
                max_queries=max_queries,
                config_base_dir=str(config.resolve().parent),
            )
        else:
            pipeline, module = _load_evaluate_target(str(target))
            query_rows, corpus_map, qrel_map = _evaluate_inputs(module, queries, corpus, qrels)
            if any("=" not in item for item in provenance):
                raise ValueError("--provenance expects KEY=VALUE.")
            report = ro.evaluate(
                pipeline,
                queries=query_rows,
                corpus=corpus_map,
                qrels=qrel_map,
                k=k,
                name=name,
                db_path=db or ".retobs/results.db",
                max_queries=max_queries,
                provenance=dict(item.split("=", 1) for item in provenance) or None,
                chunk_map=_read_chunk_map(chunk_map) if chunk_map else None,
            )
    except Exception as error:
        console.print(f"[red]Evaluation failed:[/red] {error}")
        raise typer.Exit(1)

    selected = format.lower()
    renderers = {
        "terminal": report.to_markdown,
        "json": report.to_json,
        "markdown": report.to_markdown,
        "md": report.to_markdown,
        "html": report.to_html,
    }
    if selected not in renderers:
        console.print("[red]--format must be terminal, json, markdown, or html.[/red]")
        raise typer.Exit(1)
    if output:
        report.write(output, format="md" if selected == "terminal" else selected)
        console.print(f"[green]Report:[/green] {output.resolve()}")
        console.print(f"[bold]Verdict:[/bold] {report.report.verdict}")
        console.print(f"[bold]Next:[/bold] {report.report.next_action}")
        console.print(f"[bold]Dashboard:[/bold] {report.report.dashboard_url}")
    else:
        typer.echo(renderers[selected]())
    completed = (report.manifest.get("counts") or {}).get("completed")
    if completed == 0:
        # Exit code 1: a run in which every query failed has produced no evidence, and the
        # first traceback is the only thing that explains why.
        evidence = _failed_run_evidence(report)
        if selected == "json" and not output:
            typer.echo(evidence, err=True)
        else:
            typer.echo(evidence)
        raise typer.Exit(1)


def _failed_run_evidence(report, tail_lines: int = 5) -> str:
    tracebacks = report.error_tracebacks
    lines = ["## Evidence", "", "No query completed; metrics are unavailable."]
    if tracebacks:
        tail = "\n".join(tracebacks[0].strip().splitlines()[-tail_lines:])
        lines.extend(["", f"First failure (last {tail_lines} lines of the traceback):", "", "```", tail, "```"])
    return "\n".join(lines)


@app.command("report")
def report_cmd(
    run_id: str = typer.Argument(..., help="Run ID."),
    db: str = typer.Option(".retobs/results.db", "--db", help="SQLite result database."),
    format: str = typer.Option("terminal", "--format", help="terminal|json|markdown|html"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write report artifact."),
) -> None:
    """Render a persisted run through the canonical report contract."""
    from retrieval_observatory.sdk.report import _run_sync, load_run_report

    try:
        report = _run_sync(load_run_report(run_id, db))
    except Exception as error:
        console.print(f"[red]Cannot build report:[/red] {error}")
        raise typer.Exit(1)
    selected = format.lower()
    if output:
        report.write(output, format="md" if selected == "terminal" else selected)
        console.print(f"[green]Report:[/green] {output.resolve()}")
        return
    if selected == "json":
        typer.echo(report.to_json())
    elif selected in ("terminal", "markdown", "md"):
        typer.echo(report.to_markdown())
    elif selected == "html":
        typer.echo(report.to_html())
    else:
        console.print("[red]--format must be terminal, json, markdown, or html.[/red]")
        raise typer.Exit(1)


def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to experiment YAML config."),
    skip_smoke_test: bool = typer.Option(False, "--skip-smoke-test", help="Skip ID consistency smoke test."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass result cache; re-run all queries."),
    latency_budget_ms: Optional[int] = typer.Option(None, "--latency-budget-ms", help="Latency budget per query in ms. If set, prints a verdict against stage deltas."),
) -> None:
    """Deprecated alias for `retobs evaluate --config`."""
    console.print("[yellow]Deprecated:[/yellow] use `retobs evaluate --config <path>` (`run` is ).")
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
    console.print(f"[dim]Next: retobs inspect-query {run_id} <query_id> --db {cfg.output.db_path}[/dim]")

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
    run_id_1: str = typer.Argument(..., help="Baseline run ID"),
    run_id_2: str = typer.Argument(..., help="Candidate run ID"),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path"),
    format: str = typer.Option("terminal", "--format", help="terminal|json|markdown|html"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write the comparison artifact."),
    policy: Optional[Path] = typer.Option(None, "--policy", help="Local release-policy YAML path."),
    fail_on: str = typer.Option("never", "--fail-on", help="never|fail|hold-or-block-or-fail"),
    artifacts: Optional[Path] = typer.Option(
        None, "--artifacts", help="Directory for release-audit.json and release-audit.html."
    ),
) -> None:
    """Compare an explicit baseline and candidate through the canonical validity/statistics contract.

    Exit status: 0 PASS (or not gated), 1 FAIL, 2 BLOCK, 3 HOLD when --fail-on selects the
    decision; 64 invalid usage; 70 the comparison could not be produced (no decision).
    """
    from retrieval_observatory.release.audit import EXIT_CODES, render_audit_html

    aliases = {
        "regression": "fail",
        "regression-or-no-decision": "hold-or-block-or-fail",
    }
    if fail_on in aliases:
        replacement = aliases[fail_on]
        console.print(
            f"[yellow]Deprecated:[/yellow] --fail-on {fail_on}; use --fail-on {replacement}."
        )
        fail_on = replacement
    allowed = {"never", "fail", "hold-or-block-or-fail"}
    if fail_on not in allowed:
        console.print(f"[red]--fail-on must be one of: {', '.join(sorted(allowed))}.[/red]")
        raise typer.Exit(64)
    report = asyncio.run(
        _compare(run_id_1, run_id_2, db_path, format=format, output=output, policy=policy)
    )
    if artifacts is not None:
        artifacts.mkdir(parents=True, exist_ok=True)
        audit = report.audit or {}
        json_path = artifacts / "release-audit.json"
        html_path = artifacts / "release-audit.html"
        json_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        html_path.write_text(render_audit_html(audit), encoding="utf-8")
        console.print(f"[green]Audit:[/green] {json_path.resolve()}")
        console.print(f"[green]Audit:[/green] {html_path.resolve()}")
    gated = {"never": set(), "fail": {"FAIL"}, "hold-or-block-or-fail": {"HOLD", "BLOCK", "FAIL"}}[fail_on]
    if report.verdict in gated:
        raise typer.Exit(EXIT_CODES[report.verdict])


async def _compare(
    run_id_1: str,
    run_id_2: str,
    db_path: str,
    *,
    format: str = "terminal",
    output: Optional[Path] = None,
    policy: Optional[Path] = None,
):
    from retrieval_observatory.sdk.report import load_comparison_report

    selected = format.lower()
    if selected not in {"terminal", "json", "markdown", "md", "html"}:
        console.print("[red]--format must be terminal, json, markdown, or html.[/red]")
        raise typer.Exit(64)
    try:
        report = await load_comparison_report(run_id_1, run_id_2, db_path, policy=policy)
    except Exception as error:
        console.print(f"[red]Comparison failed:[/red] {error}")
        raise typer.Exit(70)
    renderers = {
        "terminal": report.to_markdown,
        "json": report.to_json,
        "markdown": report.to_markdown,
        "md": report.to_markdown,
        "html": report.to_html,
    }
    if output:
        report.write(output, format="md" if selected == "terminal" else selected)
        console.print(f"[green]Report:[/green] {output.resolve()}")
        console.print(f"[bold]Verdict:[/bold] {report.verdict}")
        console.print(f"[bold]Next:[/bold] {report.next_action}")
    else:
        typer.echo(renderers[selected]())
    return report


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
    host: str = typer.Option("127.0.0.1", "--host"),
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
        if host not in ("127.0.0.1", "::1", "localhost"):
            console.print("[yellow]Warning: dashboard read APIs are unauthenticated; bind remotely only on a trusted network.[/yellow]")
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
    project_root: Path = typer.Argument(Path(".")),
    phase: str = typer.Option("plan", "--phase", help="plan | apply | verify | revert."),
    plan_file: Optional[Path] = typer.Option(None, "--plan", help="Reviewed plan JSON: required by apply; plan re-plans from it (patches regenerated)."),
    output: Optional[Path] = typer.Option(None, "--output"),
    db: str = typer.Option(".retobs/results.db", "--db", help="Trace database; a relative path resolves against the project root."),
    policy: Optional[Path] = typer.Option(None, "--policy", help="Local release-policy YAML for verify preflight."),
    framework: Optional[str] = typer.Option(None, "--framework", help="Override detection: python, fastapi, langchain, llamaindex, http."),
) -> None:
    """Plan, apply, verify, or revert one canonical project integration."""
    from retrieval_observatory.integrations.model import IntegrationOptions, IntegrationPhase, IntegrationPlan
    from retrieval_observatory.integrations.service import integrate_project
    try:
        selected = IntegrationPhase(phase)
        if plan_file:
            reviewed_payload = json.loads(plan_file.read_text())
            reviewed = IntegrationPlan.from_dict(reviewed_payload.get("plan", reviewed_payload))
        else:
            reviewed = None
        payload = asyncio.run(
            integrate_project(
                project_root,
                selected,
                IntegrationOptions(reviewed, db, str(policy) if policy else None, framework),
            )
        ).to_dict()
    except (ValueError, OSError) as error:
        console.print(f"[red]Integration failed:[/red] {error}")
        raise typer.Exit(1)
    serialized = json.dumps(payload, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    else:
        typer.echo(serialized)
    if payload["status"] == "failed":
        raise typer.Exit(1)


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

    # Integration verification checklist (Pillar 4) against the latest run, if any.
    if db_path.is_file():
        try:
            import asyncio as _asyncio

            from retrieval_observatory.integrations.verify import verify_integration

            report = _asyncio.run(verify_integration(db_path=str(db_path)))
            for c in report.get("checks", []):
                if c["status"] == "error":
                    check(f"integration: {c['name']}", False, c["detail"])
                else:
                    mark = "[green]✓[/green]" if c["status"] == "ok" else "[yellow]![/yellow]"
                    console.print(f"{mark} integration: {c['name']} — {c['detail']}")
        except Exception as e:  # pragma: no cover - doctor should never hard-fail here
            check("integration checks", False, str(e))

    try:
        from retrieval_observatory.mcp.server import build_server

        srv = build_server()
        import asyncio

        tools = asyncio.run(srv.list_tools())
        names = {t.name for t in tools}
        check("MCP tools registered", "integrate_project" in names and "benchmark_config" in names, f"{len(names)} tools")
    except Exception as e:
        check("MCP tools registered", False, str(e))

    if not ok:
        raise typer.Exit(1)
    console.print("[green]All checks passed.[/green]")


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

    label_order = ["candidate_miss", "reranker_drop", "not_retrieved_by_any_pipeline", "qrel_not_in_corpus", "corpus_identity_unknown", "lexical_mismatch", "semantic_mismatch", "unstable"]
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


@app.command("inspect-query")
def inspect_query_cmd(
    run_id: str = typer.Argument(..., help="Run ID."),
    query_id: str = typer.Argument(..., help="Query ID."),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
    format: str = typer.Option("terminal", "--format", help="terminal|json"),
) -> None:
    """Inspect one run-scoped query evidence chain."""
    asyncio.run(_inspect_query_contract(run_id, query_id, db_path, format))


async def _inspect_query_contract(run_id: str, query_id: str, db_path: str, format: str) -> None:
    from retrieval_observatory.evidence import build_query_evidence
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    try:
        evidence = await build_query_evidence(
            store,
            db_id=Path(db_path).stem,
            run_id=run_id,
            query_id=query_id,
        )
    except LookupError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)
    if format == "json":
        typer.echo(json.dumps(evidence, indent=2, sort_keys=True, default=str))
        return
    if format != "terminal":
        console.print("[red]--format must be terminal or json.[/red]")
        raise typer.Exit(2)

    console.print(f"[bold]Query:[/bold] {query_id}  [dim](run {run_id})[/dim]")
    console.print(evidence["query"].get("text") or "[dim]Query text unavailable[/dim]")
    ground_truth = evidence["ground_truth"]
    console.print(
        f"[bold]Ground truth:[/bold] {ground_truth['evidence_class']} · "
        f"{len(ground_truth['relevant_doc_ids'])} relevant document(s)"
    )
    warnings = evidence["evidence_health"]["warnings"]
    if warnings:
        console.print("[yellow]Partial evidence:[/yellow] " + "; ".join(warnings))
    table = Table(title="Operator traces")
    table.add_column("Pipeline")
    table.add_column("Status")
    table.add_column("Operators", justify="right")
    table.add_column("Wall latency", justify="right")
    for trace in evidence["traces"]:
        table.add_row(
            str(trace.get("pipeline_id")),
            str(trace.get("status")),
            str(len(trace.get("spans", []))),
            f"{float(trace.get('total_latency_ms', 0)):.1f} ms",
        )
    console.print(table)
    console.print(
        f"[bold]Next:[/bold] retobs serve --db {db_path}  "
        f"[dim]→ #/runs/{run_id}/queries/{query_id}[/dim]"
    )


def _investigation_request(run_id: str, pipeline_id: Optional[str], k: Optional[int], unit: str, **extra: Optional[str]):
    from retrieval_observatory.evidence import InvestigationRequest

    return InvestigationRequest.from_mapping({"run_id": run_id, "pipeline_id": pipeline_id, "k": k, "unit": unit, **extra})


@app.command("inspect-document")
def inspect_document_cmd(
    run_id: str = typer.Argument(..., help="Run ID."),
    entity: str = typer.Argument(..., help="Evaluation entity as namespace:id, or a bare id (namespace 'default')."),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
    pipeline_id: Optional[str] = typer.Option(None, "--pipeline", "-p", help="Pipeline ID (required when the run has several)."),
    k: Optional[int] = typer.Option(None, "--k", help="Evaluation cutoff (defaults to the run's first recall@k)."),
    unit: str = typer.Option("document", "--unit", help="document|chunk"),
    format: str = typer.Option("terminal", "--format", help="terminal|json"),
) -> None:
    """Inspect one evaluation entity's journey across every query of a run."""
    if format not in ("terminal", "json"):
        console.print("[red]--format must be terminal or json.[/red]")
        raise typer.Exit(2)
    from retrieval_observatory.evidence import InvestigationError, inspect_document
    from retrieval_observatory.store.sqlite import SQLiteStore

    async def _load():
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        return await inspect_document(store, _investigation_request(run_id, pipeline_id, k, unit, entity=entity))

    try:
        envelope = asyncio.run(_load())
    except InvestigationError as error:
        console.print(f"[red]{error.code}: {error.detail}[/red]")
        raise typer.Exit(1)
    if format == "json":
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        return
    scope = envelope["scope"]
    console.print(f"[bold]Entity:[/bold] {entity}  [dim](run {scope['run_id']} · pipeline {scope['pipeline_id']} · k={scope['k']})[/dim]")
    table = Table(title="Queries")
    for column in ("Query", "Judgment", "Outcome", "Final rank", "Loss boundary"):
        table.add_column(column)
    for row in envelope["rows"]:
        table.add_row(row["query_id"], row["judgment"], row["outcome"], str(row.get("final_rank") or "-"), str(row.get("loss_boundary") or "-"))
    console.print(table)
    for finding in envelope["findings"]:
        console.print(f"[yellow]{finding['code']}:[/yellow] {finding['detail']} → {finding['action']}")


@storage_app.command("migrate")
def storage_migrate(
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Copy the file before changing it."),
) -> None:
    """Bring the results database to the current schema (additive; keeps every row)."""
    from retrieval_observatory.store.migrate import migrate_database

    typer.echo(json.dumps(migrate_database(Path(db_path), backup=backup), indent=2, sort_keys=True))


@storage_app.command("index")
def storage_index(
    run_id: str = typer.Argument(..., help="Run ID to index."),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path", help="SQLite database path."),
    pipeline_id: Optional[str] = typer.Option(None, "--pipeline", "-p", help="Pipeline ID (required when the run has several)."),
    k: Optional[int] = typer.Option(None, "--k", help="Evaluation cutoff (defaults to the run's first recall@k)."),
    unit: str = typer.Option("document", "--unit", help="document|chunk"),
) -> None:
    """Project a run's traces into investigation rows (the explicit write behind the Investigate views)."""
    from retrieval_observatory.evidence import InvestigationError, build_projection, resolve_scope
    from retrieval_observatory.store.sqlite import SQLiteStore

    async def _index():
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        resolved = await resolve_scope(store, _investigation_request(run_id, pipeline_id, k, unit))
        return await build_projection(
            store, resolved.run_id, resolved.pipeline_id, resolved.spec, judgments=resolved.judgments, chunk_map=resolved.chunk_map
        )

    try:
        meta = asyncio.run(_index())
    except InvestigationError as error:
        console.print(f"[red]{error.code}: {error.detail}[/red]")
        raise typer.Exit(1)
    console.print(
        f"Indexed {meta['row_count']} row(s) from {meta['trace_count']} trace(s) for run {meta['run_id']} "
        f"pipeline {meta['pipeline_id']} (evaluation {meta['evaluation_digest'][:12]})."
    )


def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
    query_id: str = typer.Option(..., "--query", "-q", help="Query ID to inspect"),
    pipeline_id: Optional[str] = typer.Option(None, "--pipeline", "-p", help="Pipeline ID (defaults to all)"),
    db_path: str = typer.Option(".retobs/results.db", "--db", "--db-path"),
) -> None:
    """Deprecated alias for `retobs inspect-query`."""
    console.print("[yellow]Deprecated:[/yellow] use `retobs inspect-query RUN QUERY` (`inspect` is ).")
    asyncio.run(_inspect(run_id, query_id, pipeline_id, db_path))


async def _inspect(run_id: str, query_id: str, pipeline_id: Optional[str], db_path: str) -> None:
    import aiosqlite
    import json as _json
    from retrieval_observatory.store.base import TraceQuery
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    traces = await store.list_traces(TraceQuery(run_id=run_id, query_id=query_id, pipeline_id=pipeline_id))
    stage_rows = [
        {
            "pipeline_id": trace.pipeline_id,
            "stage_index": index,
            "stage_id": span.op_id,
            "status": span.status,
            "latency_ms": span.latency_ms,
            "retrieved_doc_ids_json": _json.dumps([candidate.doc_id for candidate in span.outputs]),
            "retrieved_scores_json": _json.dumps([candidate.score for candidate in span.outputs]),
            "error_traceback": span.error,
        }
        for trace in traces
        for index, span in enumerate(trace.spans)
    ]

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

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
# Starter config for the retobs reliability demo Test Sets dataset.
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


# ---------------------------------------------------------------------------
# Demo command — deterministic golden-fixture runs, no models, network, or API keys
# ---------------------------------------------------------------------------

# The baseline's recency filter drops lexical hits scoring below 0.85, which loses the only
# path of kb:doc-guide for q-outage; the validation run restores the golden 0.30 floor.
DEMO_VARIANTS = (
    ("baseline", "golden-demo-baseline", "golden-hybrid@recency-min-score-0.85", {"min_year": 2023, "min_score": 0.85}),
    ("validation", "golden-demo-validation", "golden-hybrid@recency-min-score-0.30", None),
)


@app.command()
def demo(
    output_dir: Path = typer.Option(Path(".retobs/demo"), "--output-dir", "-o", help="Directory for the demo manifest."),
    db: str = typer.Option(".retobs/demo/results.db", "--db", "--db-path", help="SQLite DB to write the demo runs into."),
    n_traces: Optional[int] = typer.Option(None, "--n-traces", help="Ignored; accepted for older invocations. The demo seeds no production traces."),
    keep_db: bool = typer.Option(False, "--keep-db", help="Append to an existing DB instead of starting fresh."),
) -> None:
    """Evaluate a deterministic baseline and its repaired candidate on the golden hybrid pipeline.

    No models, network, or API keys. Writes two runs plus demo_manifest.json.
    After completion: retobs serve --db <db>  →  http://localhost:4000
    """
    if n_traces is not None:
        console.print("[dim]--n-traces is ignored: the demo seeds no production traces.[/dim]")
    asyncio.run(_demo(output_dir=str(output_dir), db_path=db, keep_db=keep_db))


async def _demo_run(store, experiment_name: str, deployment_revision: str, recency_rule) -> str:
    """Evaluate the golden pipeline once through the shared runner and return the run id."""
    from retrieval_observatory.config.schema import (
        DatasetConfig,
        ExecutionConfig,
        ExperimentConfig,
        ExperimentMeta,
        MetricsConfig,
        PipelineConfig,
        ReleaseIdentityConfig,
        StageConfig,
    )
    from retrieval_observatory.datasets.judgments import JudgmentSet
    from retrieval_observatory.examples import golden_fixture as golden
    from retrieval_observatory.pipeline.factory import build_pipeline
    from retrieval_observatory.runner.execute import execute_benchmark
    from retrieval_observatory.sdk.wrappers import FunctionRetriever
    from retrieval_observatory.types import PipelineResult

    pipeline_id = "golden-hybrid"
    queries = golden.queries()
    by_text = {query.text: query for query in queries}
    rule = recency_rule or golden.RECENCY_RULE

    def retrieve(text: str) -> PipelineResult:
        query = by_text[text]
        _, trace = golden.run_pipeline(query, rule)
        trace.pipeline_id = pipeline_id
        return PipelineResult(query.query_id, pipeline_id, [], 0.0, "OK", trace=trace)

    cfg = ExperimentConfig(
        experiment=ExperimentMeta(name=experiment_name),
        dataset=DatasetConfig(name="golden"),
        pipelines=[PipelineConfig(id=pipeline_id, stages=[StageConfig(type="adapter.import", retriever_id=pipeline_id)])],
        metrics=MetricsConfig(recall_at_k=[golden.EVALUATION_SPEC["k"]], ndcg_at_k=[golden.EVALUATION_SPEC["k"]]),
        execution=ExecutionConfig(concurrency=1, cache_results=False),
        release_identity=ReleaseIdentityConfig(deployment_revision=deployment_revision, corpus_revision="kb@1"),
    )
    artifacts = await execute_benchmark(
        cfg=cfg,
        dataset=None,
        queries=queries,
        qrels={},
        corpus={f"{namespace}:{chunk_id}": entry["title"] for (namespace, chunk_id), entry in golden.CORPUS.items()},
        pipelines=[build_pipeline(pipeline_id=pipeline_id, stages=[FunctionRetriever(retrieve, pipeline_id)], k_per_stage=[golden.SELECT_BUDGET])],
        store=store,
        no_cache=True,
        chunk_map=golden.chunk_map(),
        evaluation_k=golden.EVALUATION_SPEC["k"],
        judgments=JudgmentSet.from_records(golden.judgment_records()),
    )
    return artifacts.run_id


async def _demo(output_dir: str, db_path: str, keep_db: bool = False) -> dict:
    import shutil

    from retrieval_observatory.examples import golden_fixture
    from retrieval_observatory.store.sqlite import SQLiteStore

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    db_file = Path(db_path)
    if db_file.exists() and not keep_db:
        db_file.unlink()
        console.print(f"[dim]Removed existing demo DB: {db_path}[/dim]")
    db_file.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path=db_path)
    await store.init_db()

    console.print("[bold]retobs demo[/bold] — deterministic demo data (golden hybrid fixture: 3 queries, no models or network)")
    run_ids: dict = {}
    for role, experiment_name, revision, rule in DEMO_VARIANTS:
        run_ids[role] = await _demo_run(store, experiment_name, revision, rule)
        console.print(f"  [green]✓[/green] {role:<10} {run_ids[role]}  ({revision})")

    # The packaged release policy that resolves against these runs, copied beside the manifest.
    policy = out / "release-policy-golden-v3.yaml"
    shutil.copyfile(Path(golden_fixture.__file__).with_name(policy.name), policy)
    manifest = {
        "data": "deterministic demo data",
        "baseline_run_id": run_ids["baseline"],
        "validation_run_id": run_ids["validation"],
        "candidate_run_id": run_ids["validation"],
        "sample_query_id": "q-outage",
        "repaired_document": "kb:doc-guide",
        "db_path": str(db_file.resolve()),
        "policy_path": str(policy.resolve()),
        "experiment_names": {role: experiment_name for role, experiment_name, _, _ in DEMO_VARIANTS},
    }
    (out / "demo_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    baseline, validation = run_ids["baseline"], run_ids["validation"]
    console.print(
        "\nBaseline: q-refund's kb:doc-policy survives only the dense branch (its lexical chunks are filtered), "
        "and q-outage's relevant kb:doc-guide is lost at recency_filter (min_score)."
    )
    console.print("Validation: the recency filter's min_score is restored, so kb:doc-guide is delivered.")
    console.print("\n[bold]Next:[/bold]")
    console.print(f"  retobs compare {baseline} {validation} --db {db_path} --policy {policy}")
    console.print(f"  retobs inspect-document {baseline} kb:doc-guide --db {db_path}")
    console.print(f"  retobs inspect-query {validation} q-outage --db {db_path}")
    console.print(f"  retobs serve --db {db_path}")
    return manifest



if __name__ == "__main__":
    app()
