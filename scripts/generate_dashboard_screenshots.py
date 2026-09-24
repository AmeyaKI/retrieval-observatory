#!/usr/bin/env python3
"""Generate publication dashboard screenshots from publish SQLite DBs.

Writes PNGs to results/screenshots/ (embedded in BENCHMARK_ANALYSIS.md and README).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from retrieval_observatory.dashboard.api import _compute_stage_contributions
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.store.sqlite import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "screenshots"

# Sorted pipeline_id order → Okabe-Ito palette
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]

RUNS = [
    ("nfcorpus", ".retobs/publish_sweep_nfcorpus.db", "37d3a79c"),
]


def _pipeline_colors(pipeline_ids: list[str]) -> dict[str, str]:
    sorted_ids = sorted(set(pipeline_ids))
    return {pid: PALETTE[i % len(PALETTE)] for i, pid in enumerate(sorted_ids)}


async def _load_stage_contribution(db_path: str, run_id: str):
    store = SQLiteStore(db_path=db_path)
    engine = MetricsEngine()
    agg = await engine.aggregate(run_id, store)
    rows = await store.get_metrics(run_id)
    contribs = _compute_stage_contributions(agg, rows)
    return [c for c in contribs if c.get("from_pipeline") == "bm25" and c.get("to_pipeline") == "bm25__rerank"]


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

    stage_contrib = await _load_stage_contribution(str(ROOT / nfc_db), nfc_run)

    plot_stage_attribution(stage_contrib, OUT / "stage-attribution-nfcorpus.png")

    # Recall funnel: simple bar chart of recall@10 by pipeline final stage
    store = SQLiteStore(db_path=str(ROOT / nfc_db))
    engine = MetricsEngine()
    agg = await engine.aggregate(nfc_run, store)
    final: dict[str, tuple[int, float]] = {}  # pipeline -> (final stage, recall@10 mean)
    for value in agg.values():
        stage = value.get("stage_index", -1)
        if value.get("branch_id") or stage < 0 or (value["metric_name"], value.get("k", 0)) != ("recall", 10):
            continue
        if stage >= final.get(value["pipeline_id"], (-1, 0.0))[0]:
            final[value["pipeline_id"]] = (stage, value["mean"])
    pids = sorted(final.keys())
    recalls = [final[p][1] for p in pids]
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
