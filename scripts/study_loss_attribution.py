#!/usr/bin/env python3
"""Grid driver for the pre-registered study in results/study/PREREGISTRATION.md.

One cell = one pipeline on one dataset. Every cell runs through `execute_benchmark`, the
same executor `retobs evaluate` uses, into `results/study/results.db`; the cell's statistics
(PREREGISTRATION.md §3, computed by `analysis/loss_attribution.py`) and the counterfactual
marginal contributions are written to `results/study/cells/<cell>.json`. A cell whose JSON
exists is skipped, so the driver can be rerun after an interruption.

Usage:
    python scripts/study_loss_attribution.py --list
    python scripts/study_loss_attribution.py --estimate-only
    python scripts/study_loss_attribution.py                       # the whole grid
    python scripts/study_loss_attribution.py --cells nfcorpus__bm25_only fiqa__hybrid_rerank

Smoke test (never writes under results/study/):
    python scripts/study_loss_attribution.py --max-queries 4 --out-dir /tmp/study-smoke --db /tmp/study-smoke.db
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# torch and faiss each bundle an OpenMP runtime; on macOS conda environments loading both
# segfaults inside the dense lane (FUTURE_WORK.md, demo ergonomics). Overridable.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = ROOT / "results" / "study"
CELLS_DIR = STUDY_DIR / "cells"
DEFAULT_DB = STUDY_DIR / "results.db"
CACHE_DIR = ROOT / ".retobs" / "study" / "cache"
FLAGSHIP_DIR = ROOT / "results" / "flagship_demo"
HOTPOT_MANIFEST = STUDY_DIR / "hotpotqa_query_manifest.json"

DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
BEIR_DATASETS = ("nfcorpus", "scifact", "fiqa")
BEIR_PIPELINES = ("bm25_only", "dense_only", "rrf_hybrid", "hybrid_rerank")
RECONCILIATION_PIPELINE = "bm25_rerank"
HOTPOT_DATASET = "hotpotqa"
HOTPOT_PIPELINE = "hotpot_routed"
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 17
DELIVERY_K = 10
MAX_GRID_HOURS = 12.0  # PREREGISTRATION.md §5: beyond this the subsampling rule applies (as an amendment)
PROBE_QUERIES = 5


@dataclass(frozen=True)
class Cell:
    dataset: str
    pipeline: str
    reconciliation_only: bool = False

    @property
    def id(self) -> str:
        return f"{self.dataset}__{self.pipeline}"


def grid() -> list[Cell]:
    cells = [Cell(dataset, pipeline) for dataset in BEIR_DATASETS for pipeline in BEIR_PIPELINES]
    cells.append(Cell("fiqa", RECONCILIATION_PIPELINE, reconciliation_only=True))
    cells.append(Cell(HOTPOT_DATASET, HOTPOT_PIPELINE))
    return cells


def cell_path(cell: Cell, out_dir: Path) -> Path:
    return out_dir / f"{cell.id}.json"


# --------------------------------------------------------------------------------------
# BEIR cells: pipelines 1–4 and the reconciliation cell, declared as graphs (§5)
# --------------------------------------------------------------------------------------


def beir_graph(pipeline: str):
    from retrieval_observatory.config.schema import GraphNodeConfig, GraphPipelineConfig

    node = GraphNodeConfig
    bm25 = node(id="bm25", type="adapter.bm25", op_type="SOURCE", config={"k": 100})
    dense = node(
        id="dense", type="adapter.hf_biencoder", op_type="SOURCE",
        config={"model": DENSE_MODEL, "k": 100, "batch_size": 64, "cache_dir": str(CACHE_DIR)},
    )
    fuse = node(id="fuse", op="fuse", op_type="FUSE", inputs=["bm25", "dense"], config={"rrf_k": 60, "top_k": 100, "fetch_k": 100})

    def rerank(parent: str):
        # k=100: the cross-encoder scores every input and returns the full re-order, so a
        # gold pushed past 10 keeps a recorded rank. Scoring cost is the same as returning 10.
        return node(
            id="rerank", type="adapter.hf_crossencoder", op_type="RERANK", inputs=[parent],
            config={"model": CROSS_ENCODER, "k": 100, "batch_size": 32},
        )

    nodes = {
        "bm25_only": [bm25],
        "dense_only": [dense],
        "rrf_hybrid": [bm25, dense, fuse],
        "hybrid_rerank": [bm25, dense, fuse, rerank("fuse")],
        RECONCILIATION_PIPELINE: [bm25, rerank("bm25")],
    }[pipeline]
    return GraphPipelineConfig(id=pipeline, nodes=nodes)


def beir_config(dataset: str, graph, db_path: Path, build: dict[str, str]):
    from retrieval_observatory.config.schema import (
        DatasetConfig, ExecutionConfig, ExperimentConfig, ExperimentMeta, MetricsConfig, OutputConfig,
        ReleaseIdentityConfig,
    )

    node_types = {n.type for n in graph.nodes}
    return ExperimentConfig(
        experiment=ExperimentMeta(name=f"study-{dataset}-{graph.id}"),
        dataset=DatasetConfig(name=f"beir/{dataset}", split="test"),
        graphs=[graph],
        # Quality metrics only: the study makes no latency claims (PREREGISTRATION.md §5).
        metrics=MetricsConfig(recall_at_k=[10], ndcg_at_k=[10], precision_at_k=[10], mrr=True, latency_percentiles=[]),
        execution=ExecutionConfig(concurrency=1, seed=BOOTSTRAP_SEED, cache_results=False, timeout_seconds=600),
        output=OutputConfig(store="sqlite", db_path=str(db_path)),
        release_identity=ReleaseIdentityConfig(
            service_id="retobs-study",
            deployment_revision=build["git_sha"],
            embedding_model_revision=DENSE_MODEL if "adapter.hf_biencoder" in node_types else None,
            reranker_model_revision=CROSS_ENCODER if "adapter.hf_crossencoder" in node_types else None,
        ),
    )


def _beir_setup(cell: Cell, db_path: Path, build: dict[str, str]):
    from retrieval_observatory.datasets.beir import BEIRDataset
    from retrieval_observatory.pipeline.factory import build_dag_from_config

    dataset = BEIRDataset(dataset_name=f"beir/{cell.dataset}", split="test")
    queries, qrels = dataset.load()
    graph = beir_graph(cell.pipeline)
    cfg = beir_config(cell.dataset, graph, db_path, build)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pipeline = build_dag_from_config(graph.model_dump(), corpus=dataset.corpus)
    return dataset, queries, qrels, dataset.corpus, cfg, pipeline, {"index_cache_dir": str(CACHE_DIR)}


# --------------------------------------------------------------------------------------
# HotpotQA cell: the flagship routed pipeline, unchanged (§5)
# --------------------------------------------------------------------------------------


def _hotpot_setup(db_path: Path, max_queries: int | None, log: Callable[..., None]):
    if str(FLAGSHIP_DIR) not in sys.path:
        sys.path.insert(0, str(FLAGSHIP_DIR))
    from pipeline import DemoCorpus, PipelineSettings, build_config, build_pipeline  # results/flagship_demo
    from run import load_dataset

    data_dir = FLAGSHIP_DIR / "data"
    if not (data_dir / "corpus.jsonl").exists():
        raise SystemExit(f"HotpotQA subset missing: run `python {FLAGSHIP_DIR / 'build_corpus.py'}` first (seed 20260803, n=1300).")
    settings = PipelineSettings()
    corpus = DemoCorpus.load(data_dir)
    dataset, queries, qrels = load_dataset(data_dir, settings.final_k)
    source_manifest = json.loads((data_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    if max_queries is None:
        _write_hotpot_manifest([q.query_id for q in queries], source_manifest, log)
    cfg = build_config(corpus, settings, experiment_name=f"study-{HOTPOT_DATASET}-{HOTPOT_PIPELINE}")
    cfg.output.db_path = str(db_path)
    cfg.metrics.latency_percentiles = []  # quality only; the pipeline itself is unchanged
    pipeline = build_pipeline(corpus, settings)
    extra = {
        "index_cache_dir": "~/.retobs/faiss_cache (the flagship pipeline's own cache, keyed by corpus and model)",
        "settings": asdict(settings),
        "subset": {
            "queries": source_manifest["counts"]["queries"],
            "corpus_documents": source_manifest["counts"]["corpus_documents"],
            "seed": source_manifest["sampling"]["seed"],
            "fingerprints": source_manifest["fingerprints"],
        },
    }
    return dataset, queries, qrels, corpus.index_text, cfg, pipeline, extra


def _write_hotpot_manifest(query_ids: list[str], source_manifest: dict, log: Callable[..., None]) -> None:
    """Commit the ordered query list before the cell runs; refuse to run against a different one."""
    payload = {
        "dataset": "hotpotqa/hotpot_qa distractor validation, sampled by results/flagship_demo/build_corpus.py",
        "seed": source_manifest["sampling"]["seed"],
        "n_queries": len(query_ids),
        "fingerprints": source_manifest["fingerprints"],
        "query_ids": query_ids,
    }
    if HOTPOT_MANIFEST.exists():
        existing = json.loads(HOTPOT_MANIFEST.read_text(encoding="utf-8"))
        if existing["query_ids"] != query_ids or existing["fingerprints"] != payload["fingerprints"]:
            raise SystemExit(f"{HOTPOT_MANIFEST} does not match the data on disk; refusing to run a different subset.")
        return
    HOTPOT_MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log(f"  wrote {_rel(HOTPOT_MANIFEST)} ({len(query_ids)} queries)")


# --------------------------------------------------------------------------------------
# Running a cell
# --------------------------------------------------------------------------------------


def build_info() -> dict[str, str]:
    import retrieval_observatory

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"git_sha": sha or "unknown", "retobs_version": getattr(retrieval_observatory, "__version__", "unknown")}


async def estimate_runtime(pipeline, queries, log: Callable[..., None]) -> dict[str, float]:
    """Warm the indexes on one query, time a few more, extrapolate. Nothing here is persisted."""
    started = time.perf_counter()
    await pipeline.run(replace(queries[0], query_id="__warmup__"))
    warmup = time.perf_counter() - started
    probe = queries[1 : 1 + PROBE_QUERIES] or queries[:1]
    started = time.perf_counter()
    for index, query in enumerate(probe):
        await pipeline.run(replace(query, query_id=f"__probe_{index}__"))
    per_query = (time.perf_counter() - started) / len(probe)
    estimate = per_query * len(queries)
    log(f"  warm-up {warmup:.1f}s (index build or load); probe {per_query * 1000:.0f} ms/query x {len(queries)} = ~{estimate / 60:.1f} min")
    return {"warmup_seconds": warmup, "probe_ms_per_query": per_query * 1000, "estimated_seconds": estimate}


async def run_cell(
    cell: Cell,
    *,
    db_path: Path,
    out_dir: Path,
    max_queries: int | None,
    estimate_only: bool,
    log: Callable[..., None],
) -> dict[str, Any] | None:
    from retrieval_observatory.analysis.loss_attribution import attribute_run, summarize
    from retrieval_observatory.runner.execute import execute_benchmark
    from retrieval_observatory.store.sqlite import SQLiteStore
    from retrieval_observatory.tracing.attribution import operator_marginal_contributions

    path = cell_path(cell, out_dir)
    if path.exists():
        log(f"[{cell.id}] complete, skipping ({_rel(path)})")
        return json.loads(path.read_text(encoding="utf-8"))

    log(f"[{cell.id}] preparing")
    build = build_info()
    if cell.dataset == HOTPOT_DATASET:
        dataset, queries, qrels, corpus, cfg, pipeline, extra = _hotpot_setup(db_path, max_queries, log)
    else:
        dataset, queries, qrels, corpus, cfg, pipeline, extra = _beir_setup(cell, db_path, build)
    if max_queries is not None:
        queries = queries[:max_queries]
        kept = {q.query_id for q in queries}
        qrels = {qid: rel for qid, rel in qrels.items() if qid in kept}
    log(f"  {len(queries)} queries, {len(qrels)} with judgments, corpus {len(corpus):,} docs")

    runtime = await estimate_runtime(pipeline, queries, log)
    if estimate_only:
        return {"cell": cell.id, "runtime": runtime, "n_queries": len(queries)}

    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    started = time.perf_counter()
    artifacts = await execute_benchmark(
        cfg=cfg, dataset=dataset, queries=queries, qrels=qrels, corpus=corpus, pipelines=[pipeline],
        store=store, no_cache=True, annotate_difficulty=False, log=log,
    )
    runtime["actual_seconds"] = time.perf_counter() - started
    log(f"  run {artifacts.run_id} in {runtime['actual_seconds'] / 60:.1f} min; {len(artifacts.error_samples)} errors")

    traces = await store.get_traces(artifacts.run_id)
    run_qrels = await store.get_qrels(artifacts.run_id)
    attribution = attribute_run(traces, run_qrels, k=DELIVERY_K)
    summary = summarize(attribution, n_resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED)
    op_ids = _non_source_operators(traces)
    marginal = {
        metric: [asdict(row) for row in operator_marginal_contributions(
            traces, op_ids, run_qrels, metric=metric, k=DELIVERY_K, n_bootstrap=BOOTSTRAP_RESAMPLES,
        )]
        for metric in ("ndcg", "recall")
    }
    frac = summary.self_inflicted_fraction
    log(f"  self-inflicted {_fmt(frac)}; outcomes {summary.outcome_counts}; completeness {summary.completeness}")

    payload = {
        "cell": cell.id,
        "dataset": cell.dataset,
        "pipeline": cell.pipeline,
        "reconciliation_only": cell.reconciliation_only,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "build": build,
        "run_id": artifacts.run_id,
        "experiment_name": cfg.experiment.name,
        "db_path": str(db_path),
        "max_queries": max_queries,
        "n_queries": len(queries),
        "n_queries_with_judgments": len(qrels),
        "n_traces": len(traces),
        "graph": cfg.graphs[0].model_dump(),
        **extra,
        "runtime": runtime,
        "errors": artifacts.error_samples[:5],
        "metrics": {key: row for key, row in artifacts.aggregated.items() if "latency" not in key},
        "loss": summary.to_dict(),
        "marginal": {
            "n_bootstrap": BOOTSTRAP_RESAMPLES,
            "method": "tracing.attribution.operator_marginal_contributions (sign-flip test, BH per pipeline; package default seed)",
            **marginal,
        },
        "events": [event.to_dict() for event in attribution.events],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    log(f"  wrote {path}")
    return payload


def _rel(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def _plain_log(*parts: Any, **_: Any) -> None:
    """The executor logs with rich markup; this driver prints plain text."""
    print(re.sub(r"\[/?bold\]", "", " ".join(str(part) for part in parts)))


def _non_source_operators(traces) -> list[str]:
    for trace in traces:
        if trace.status == "OK" and trace.spans:
            return [span.op_id for span in trace.spans if span.op_type != "SOURCE"]
    return []


def _fmt(rate) -> str:
    if rate.value is None:
        return f"undefined ({rate.numerator}/{rate.denominator})"
    return f"{rate.value:.3f} [{rate.ci_low:.3f}, {rate.ci_high:.3f}] ({rate.numerator}/{rate.denominator})"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    cells = grid()
    if args.cells:
        unknown = set(args.cells) - {cell.id for cell in cells}
        if unknown:
            raise SystemExit(f"unknown cells: {sorted(unknown)}; use --list")
        cells = [cell for cell in cells if cell.id in set(args.cells)]
    out_dir = Path(args.out_dir)
    db_path = Path(args.db)
    log = _plain_log
    cumulative = 0.0
    for cell in cells:
        result = await run_cell(
            cell, db_path=db_path, out_dir=out_dir, max_queries=args.max_queries,
            estimate_only=args.estimate_only, log=log,
        )
        if result and "runtime" in result and "actual_seconds" not in result["runtime"]:
            cumulative += result["runtime"]["estimated_seconds"]
            if cumulative > MAX_GRID_HOURS * 3600 and not args.estimate_only:
                raise SystemExit(
                    f"cumulative estimate {cumulative / 3600:.1f} h exceeds {MAX_GRID_HOURS} h: apply the "
                    "pre-registered subsampling rule as a dated amendment before continuing."
                )
    if args.estimate_only:
        log(f"estimated total for the cells above: ~{cumulative / 3600:.2f} h")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="print the grid and exit")
    parser.add_argument("--cells", nargs="*", help="cell ids to run (default: every cell)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="master results database")
    parser.add_argument("--out-dir", default=str(CELLS_DIR), help="per-cell JSON directory")
    parser.add_argument("--max-queries", type=int, default=None, help="smoke test only; requires --out-dir and --db outside results/study")
    parser.add_argument("--estimate-only", action="store_true", help="build indexes and print runtime estimates without running")
    args = parser.parse_args()
    if args.list:
        for cell in grid():
            print(f"{cell.id}{'  (reconciliation only)' if cell.reconciliation_only else ''}")
        return 0
    if args.max_queries is not None:
        for value in (args.out_dir, args.db):
            if Path(value).resolve().is_relative_to(STUDY_DIR):
                raise SystemExit("--max-queries is a smoke test: point --out-dir and --db outside results/study")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
