#!/usr/bin/env python3
"""Generate publication dashboard screenshots from publish SQLite DBs.

Writes PNGs to results/screenshots/ (embedded in BENCHMARK_ANALYSIS.md and README).
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from retrieval_observatory.dashboard.api import _compute_stage_contributions, _extract_final_stage_metrics
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.metrics.pareto import ParetoPipelineInput, compute_pareto_frontier
from retrieval_observatory.metrics.significance import bootstrap_ci
from retrieval_observatory.store.sqlite import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "screenshots"

# Sorted pipeline_id order → Okabe-Ito palette (matches dashboard chartColors.ts)
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]

RUNS = [
    ("nfcorpus", ".retobs/publish_sweep_nfcorpus.db", "37d3a79c"),
    ("fiqa", ".retobs/publish_sweep_fiqa.db", "0784ed30"),
]


def _pipeline_colors(pipeline_ids: list[str]) -> dict[str, str]:
    sorted_ids = sorted(set(pipeline_ids))
    return {pid: PALETTE[i % len(PALETTE)] for i, pid in enumerate(sorted_ids)}


async def _load_pareto(db_path: str, run_id: str):
    store = SQLiteStore(db_path=db_path)
    engine = MetricsEngine()
    agg = await engine.aggregate(run_id, store)
    final = _extract_final_stage_metrics(agg)
    inputs = []
    for pid, metrics in final.items():
        inputs.append(
            ParetoPipelineInput(
                pipeline_id=pid,
                stage_index=int(metrics["stage_index"]),
                ndcg10=metrics["ndcg10"],
                recall10=metrics["recall10"],
                latency_p50=metrics["latency_p50"],
                latency_p95=metrics["latency_p95"],
                cost_per_1k=None,
            )
        )
    return compute_pareto_frontier(inputs)


async def _load_classifier(db_path: str, run_id: str) -> List[Dict[str, Any]]:
    """Match dashboard classifier-calibration API: mean final-stage recall@10 per query, grouped by predicted class."""
    store = SQLiteStore(db_path=db_path)
    metrics_rows = await store.get_metrics(run_id)

    predicted_by_id: Dict[str, str] = {}
    for row in metrics_rows:
        pred = (row.get("query_metadata") or {}).get("predicted_difficulty")
        if pred:
            predicted_by_id.setdefault(row["query_id"], pred)

    if not predicted_by_id:
        raise RuntimeError(f"No classifier predictions found in {db_path} run {run_id}")

    recall_rows = [
        r for r in metrics_rows
        if r["metric_name"] == "recall" and r["k"] == 10 and r["stage_index"] >= 0
    ]
    max_stage_by_pipeline: Dict[str, int] = {}
    for r in recall_rows:
        pid = r["pipeline_id"]
        max_stage_by_pipeline[pid] = max(max_stage_by_pipeline.get(pid, -1), r["stage_index"])

    per_query_recall: Dict[str, List[float]] = defaultdict(list)
    for r in recall_rows:
        pid = r["pipeline_id"]
        if r["stage_index"] != max_stage_by_pipeline.get(pid, r["stage_index"]):
            continue
        per_query_recall[r["query_id"]].append(float(r["value"]))

    query_mean_recall = {
        qid: float(np.mean(vals)) for qid, vals in per_query_recall.items() if vals
    }

    classes: List[Dict[str, Any]] = []
    for cls in ("easy", "medium", "hard"):
        qids = [qid for qid, pred in predicted_by_id.items() if pred == cls]
        scores = [query_mean_recall[qid] for qid in qids if qid in query_mean_recall]
        if not scores:
            classes.append({"class": cls, "n": 0, "mean_recall10": None, "ci_low": None, "ci_high": None})
            continue
        ci_low, ci_high = bootstrap_ci(scores)
        classes.append({
            "class": cls,
            "n": len(scores),
            "mean_recall10": float(np.mean(scores)),
            "ci_low": ci_low,
            "ci_high": ci_high,
        })
    return classes


async def _load_stage_contribution(db_path: str, run_id: str):
    store = SQLiteStore(db_path=db_path)
    engine = MetricsEngine()
    agg = await engine.aggregate(run_id, store)
    rows = await store.get_metrics(run_id)
    contribs = _compute_stage_contributions(agg, rows)
    return [c for c in contribs if c.get("from_pipeline") == "bm25" and c.get("to_pipeline") == "bm25__rerank"]


def plot_pareto(result, title: str, out_path: Path) -> None:
    pipelines = result.pipelines
    pids = [p.pipeline_id for p in pipelines]
    colors = _pipeline_colors(pids)

    fig, ax = plt.subplots(figsize=(10, 6), dpi=120)
    fig.patch.set_facecolor("white")

    xs, ys, labels, optimal = [], [], [], []
    for p in pipelines:
        lat = p.metrics.get("latency_p50")
        ndcg = p.metrics.get("ndcg@10")
        if lat is None or ndcg is None:
            continue
        xs.append(lat)
        ys.append(ndcg)
        labels.append(p.pipeline_id)
        optimal.append(p.is_pareto_optimal)

    for x, y, label, is_opt in zip(xs, ys, labels, optimal):
        color = colors[label]
        marker = "*" if is_opt else "o"
        size = 220 if is_opt else 100
        ax.scatter(x, y, c=color, s=size, marker=marker, edgecolors="white", linewidths=0.8, zorder=3)
        ax.annotate(
            label.replace("_", " "),
            (x, y),
            textcoords="offset points",
            xytext=(8, 6),
            fontsize=9,
            color="#374151",
        )

    frontier = [p for p in pipelines if p.is_pareto_optimal]
    frontier.sort(key=lambda p: p.metrics.get("latency_p50") or 0)
    if len(frontier) >= 2:
        fx = [p.metrics["latency_p50"] for p in frontier]
        fy = [p.metrics["ndcg@10"] for p in frontier]
        ax.plot(fx, fy, color="#6366F1", linewidth=1.5, linestyle="--", alpha=0.7, zorder=2, label="Pareto frontier")

    ax.set_xscale("log")
    ax.set_xlabel("P50 Latency (ms, log scale)", fontsize=11)
    ax.set_ylabel("NDCG@10", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, alpha=0.25, linestyle="-")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    star_patch = mpatches.Patch(color="gray", label="★ Pareto optimal")
    ax.legend(handles=[star_patch], loc="lower right", framealpha=0.9, fontsize=9)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_classifier(classes: List[Dict[str, Any]], out_path: Path) -> None:
    # Match dashboard ClassifierCalibration.tsx colors
    class_colors = {"easy": "#22c55e", "medium": "#3b82f6", "hard": "#ef4444"}

    labels: List[str] = []
    values: List[float] = []
    yerr_lo: List[float] = []
    yerr_hi: List[float] = []
    colors: List[str] = []
    ns: List[int] = []

    for row in classes:
        if row.get("n", 0) == 0 or row.get("mean_recall10") is None:
            continue
        cls = row["class"]
        mean = row["mean_recall10"]
        ci_low = row.get("ci_low") if row.get("ci_low") is not None else mean
        ci_high = row.get("ci_high") if row.get("ci_high") is not None else mean
        labels.append(cls.capitalize())
        values.append(mean)
        yerr_lo.append(mean - ci_low)
        yerr_hi.append(ci_high - mean)
        colors.append(class_colors.get(cls, "#6b7280"))
        ns.append(row["n"])

    if not values:
        raise RuntimeError("Classifier calibration has no data to plot")

    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    fig.patch.set_facecolor("white")
    x = np.arange(len(labels))
    bars = ax.bar(
        x,
        values,
        color=colors,
        edgecolor="white",
        linewidth=0.8,
        yerr=[yerr_lo, yerr_hi],
        capsize=4,
        error_kw={"elinewidth": 1.2, "ecolor": "#374151"},
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Mean Recall@10 (predicted bucket)", fontsize=11)
    ax.set_xlabel("Predicted difficulty", fontsize=11)
    ax.set_title("Classifier Calibration — NFCorpus (323 queries)", fontsize=13, fontweight="bold", pad=12)
    ax.set_ylim(0, max(values) * 1.25)
    for bar, val, n in zip(bars, values, ns):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.03,
            f"{val:.3f}\n(n={n})",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_stage_attribution(contribs: list, out_path: Path) -> None:
    if not contribs:
        return
    c = contribs[0]
    deltas = c.get("deltas", {})
    names = ["recall@10", "ndcg@10", "mrr"]
    names = [n for n in names if n in deltas]
    before = [deltas[n]["before"] for n in names]
    after = [deltas[n]["after"] for n in names]
    delta_vals = [deltas[n]["absolute"] for n in names]

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
    fig.patch.set_facecolor("white")
    x = np.arange(len(names))
    width = 0.35
    ax.bar(x - width / 2, before, width, label="BM25", color="#0072B2")
    ax.bar(x + width / 2, after, width, label="BM25 → Rerank", color="#E69F00")
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10)
    ax.set_title("Stage Attribution: bm25 → bm25__rerank (NFCorpus)", fontsize=13, fontweight="bold", pad=12)
    ax.legend(framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    for i, d in enumerate(delta_vals):
        if d is not None:
            ax.text(i, max(before[i] or 0, after[i] or 0) + 0.01, f"+{d:.3f}", ha="center", fontsize=9, color="#059669")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


async def main() -> None:
    nfc_db, nfc_run = RUNS[0][1], RUNS[0][2]
    fiqa_db, fiqa_run = RUNS[1][1], RUNS[1][2]

    nfc_pareto = await _load_pareto(str(ROOT / nfc_db), nfc_run)
    fiqa_pareto = await _load_pareto(str(ROOT / fiqa_db), fiqa_run)
    classifier = await _load_classifier(str(ROOT / nfc_db), nfc_run)
    stage_contrib = await _load_stage_contribution(str(ROOT / nfc_db), nfc_run)

    plot_pareto(nfc_pareto, "Quality–Latency Tradeoff — NFCorpus (4 pipelines)", OUT / "pareto-frontier-nfcorpus.png")
    plot_pareto(fiqa_pareto, "Quality–Latency Tradeoff — FiQA (dense_only sole Pareto optimal)", OUT / "pareto-frontier-fiqa.png")
    plot_classifier(classifier, OUT / "classifier-calibration-nfcorpus.png")
    plot_stage_attribution(stage_contrib, OUT / "stage-attribution-nfcorpus.png")

    # Recall funnel: simple bar chart of recall@10 by pipeline final stage
    store = SQLiteStore(db_path=str(ROOT / nfc_db))
    engine = MetricsEngine()
    agg = await engine.aggregate(nfc_run, store)
    final = _extract_final_stage_metrics(agg)
    pids = sorted(final.keys())
    recalls = [final[p]["recall10"] for p in pids]
    colors = [_pipeline_colors(pids)[p] for p in pids]

    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    fig.patch.set_facecolor("white")
    ax.bar([p.replace("_", " ") for p in pids], recalls, color=colors, edgecolor="white")
    ax.set_ylabel("Recall@10", fontsize=11)
    ax.set_title("Final-Stage Recall@10 by Pipeline — NFCorpus", fontsize=13, fontweight="bold", pad=12)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "recall-funnel-nfcorpus.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"Wrote screenshots to {OUT}/")


if __name__ == "__main__":
    asyncio.run(main())
