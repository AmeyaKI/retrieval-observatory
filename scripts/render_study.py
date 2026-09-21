#!/usr/bin/env python3
"""Render results/study/STUDY.md from the committed per-cell JSON under results/study/cells/.

Every digit in STUDY.md comes from those files; the prose around them is this template. Pooled
statistics are recomputed from each cell's per-pair `events` with the same cluster bootstrap the
driver uses (`analysis/loss_attribution.py`: 2,000 query resamples, seed 17), clustering on
(dataset, query) so a query's golds stay together across datasets and across the two pooled
pipelines. The headline sentence is chosen by the decision rule in PREREGISTRATION.md §2, never by
eye. While any primary cell is missing the document is rendered as a labelled draft.

Usage:
    python scripts/render_study.py              # writes results/study/STUDY.md
    python scripts/render_study.py --check      # exit 1 if STUDY.md is stale
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retrieval_observatory.analysis.loss_attribution import (  # noqa: E402
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    DELIVERY_K,
    OPERATOR_CLASSES,
    Displacement,
    GoldEvent,
    Rate,
    self_inflicted_difference,
    summarize,
)

STUDY_DIR = ROOT / "results" / "study"
CELLS_DIR = STUDY_DIR / "cells"
OUT = STUDY_DIR / "STUDY.md"

BEIR = ("nfcorpus", "scifact", "fiqa")
PIPELINES = ("bm25_only", "dense_only", "rrf_hybrid", "hybrid_rerank")
HYBRID = ("rrf_hybrid", "hybrid_rerank")
PIPELINE_LABEL = {
    "bm25_only": "1 · BM25",
    "dense_only": "2 · dense",
    "rrf_hybrid": "3 · RRF hybrid",
    "hybrid_rerank": "4 · hybrid + rerank",
    "bm25_rerank": "R · BM25 + rerank",
    "hotpot_routed": "5 · routed (HotpotQA)",
}
HOTPOT = ("hotpotqa", "hotpot_routed")
# Cells re-run after the 2026-09-20 amendment (reranker scored empty text before it).
RERANK_FIX_AMENDMENT = "2026-09-20"
RERANK_CELLS = {("nfcorpus", "hybrid_rerank"), ("scifact", "hybrid_rerank"), ("fiqa", "hybrid_rerank"), ("fiqa", "bm25_rerank")}

# PREREGISTRATION.md §2.
THRESHOLD = 0.10
MIN_COMPLETENESS = 0.95
MAX_WIDTH = 0.20

# PREREGISTRATION.md §8: the prior figures, from results/BENCHMARK_ANALYSIS.md (build 0.1.0, fiqa, 648 queries).
PRIOR = {"bm25": 0.159, "dense": 0.369, "bm25_rerank": 0.260, "rrf": 0.290}


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def _load_driver():
    path = ROOT / "scripts" / "study_loss_attribution.py"
    spec = importlib.util.spec_from_file_location("study_loss_attribution", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expected_cells() -> List[Tuple[str, str]]:
    return [(cell.dataset, cell.pipeline) for cell in _load_driver().grid()]


def load_cells(cells_dir: Path = CELLS_DIR) -> Dict[Tuple[str, str], Dict[str, Any]]:
    cells = {}
    for path in sorted(cells_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cells[(payload["dataset"], payload["pipeline"])] = payload
    return cells


def events_of(cell: Dict[str, Any]) -> List[GoldEvent]:
    """Rebuild GoldEvents with dataset-qualified query ids so pooled bootstraps cluster correctly."""
    dataset = cell["dataset"]
    out = []
    for raw in cell["events"]:
        item = dict(raw)
        item["query_id"] = f"{dataset}:{item['query_id']}"
        for key in ("first_displacer", "last_displacer"):
            if item.get(key):
                item[key] = Displacement(**item[key])
        out.append(GoldEvent(**item))
    return out


def rate_of(payload: Dict[str, Any]) -> Rate:
    return Rate(**payload)


# --------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------


def pct(value: Optional[float], digits: int = 1) -> str:
    return "—" if value is None else f"{100 * value:.{digits}f}%"


def pct_ci(rate: Rate, digits: int = 1) -> str:
    if rate.value is None:
        return f"undefined (0 of {rate.denominator})"
    return f"{pct(rate.value, digits)} [{pct(rate.ci_low, digits)}, {pct(rate.ci_high, digits)}]"


def num(value: Optional[float], digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def signed(value: Optional[float], digits: int = 3) -> str:
    return "—" if value is None else f"{value:+.{digits}f}"


def pp_ci(rate: Rate, digits: int = 2) -> str:
    """A difference of two fractions, in percentage points."""
    if rate.value is None:
        return "undefined"
    return f"{100 * rate.value:+.{digits}f} pp [{100 * rate.ci_low:+.{digits}f}, {100 * rate.ci_high:+.{digits}f}]"


def detected(rate: Rate) -> Optional[str]:
    """PREREGISTRATION.md §6: a difference is detected only if its interval excludes 0."""
    if rate.value is None or rate.ci_low is None:
        return None
    if rate.ci_low > 0:
        return "up"
    if rate.ci_high < 0:
        return "down"
    return None


def table(header: Sequence[str], rows: Sequence[Sequence[str]], align: Optional[str] = None) -> str:
    align = align or "l" + "r" * (len(header) - 1)
    rule = ["---:" if a == "r" else "---" for a in align]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(rule) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------------------


def final_metric(cell: Dict[str, Any], metric: str) -> Dict[str, Any]:
    stage = cell["per_query"]["stage_index"] if "per_query" in cell else None
    if stage is None:
        stage = max(
            row["stage_index"] for row in cell["metrics"].values()
            if row.get("branch_id") is None and row["stage_index"] >= 0
        )
    return cell["metrics"][f"{cell['pipeline']}|stage{stage}|{metric}"]


def ratio_of_means(a: Dict[str, float], b: Dict[str, float]) -> Tuple[float, float, float, int]:
    """mean(a) / mean(b) on the queries both share, with a paired percentile bootstrap over queries."""
    shared = sorted(set(a) & set(b))
    x = np.array([a[q] for q in shared], dtype=float)
    y = np.array([b[q] for q in shared], dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    values = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = rng.integers(0, len(shared), size=len(shared))
        denominator = y[sample].mean()
        if denominator > 0:
            values.append(x[sample].mean() / denominator)
    low, high = np.quantile(values, [0.025, 0.975])
    return float(x.mean() / y.mean()), float(low), float(high), len(shared)


def overlaps(a: Rate, b: Rate) -> bool:
    if None in (a.ci_low, a.ci_high, b.ci_low, b.ci_high):
        return True
    return not (a.ci_low > b.ci_high or b.ci_low > a.ci_high)


def completeness(cells: Sequence[Dict[str, Any]]) -> Optional[float]:
    usable = sum(cell["loss"]["n_pairs"] for cell in cells)
    excluded = sum(item["gold_count"] for cell in cells for item in cell["loss"]["excluded_queries"])
    total = usable + excluded
    return None if total == 0 else usable / total


@dataclass
class Headline:
    branch: str
    sentence: str
    detail: str


def headline(pooled_rate: Rate, shares: Dict[str, Rate], n_queries: int, n_datasets: int, comp: Optional[float]) -> Headline:
    """PREREGISTRATION.md §2, rules applied in order."""
    f, lo, hi = pooled_rate.value, pooled_rate.ci_low, pooled_rate.ci_high
    width = None if lo is None else hi - lo
    detail = (
        f"Decision inputs: pooled fraction {pct_ci(pooled_rate)}, interval width "
        f"{pct(width)} (rule: at most {pct(MAX_WIDTH, 0)}), lineage completeness {pct(comp)} "
        f"(rule: at least {pct(MIN_COMPLETENESS, 0)}), threshold {pct(THRESHOLD, 0)}."
    )
    datasets = f"{n_datasets} dataset{'s' if n_datasets != 1 else ''}"
    if f is None or comp is None or comp < MIN_COMPLETENESS or width > MAX_WIDTH:
        return Headline("indeterminate", (
            f"Self-inflicted loss was {pct_ci(pooled_rate)} of recall@10 misses in hybrid pipelines; "
            "lineage completeness or interval width does not allow a claim."
        ), detail)
    if lo >= THRESHOLD:
        ranked = sorted(shares.items(), key=lambda item: -(item[1].value or 0.0))
        top, runner = ranked[0], ranked[1]
        by = f"most often by {top[0]}"
        if runner[1].value and overlaps(top[1], runner[1]):
            by += f", not separable from {runner[0]}"
        return Headline("positive", (
            f"Across {n_queries:,} queries on {datasets}, {pct(f)} [{pct(lo)}, {pct(hi)}] of recall@10 misses "
            "in hybrid pipelines were self-inflicted: the gold document was surfaced upstream and displaced "
            f"by a later stage, {by}."
        ), detail)
    if hi < THRESHOLD:
        return Headline("null", (
            f"Self-inflicted loss was rare: {pct(f)} [{pct(lo)}, {pct(hi)}] of recall@10 misses in hybrid "
            f"pipelines across {n_queries:,} queries on {datasets} had been surfaced upstream and displaced; "
            "the rest were never surfaced."
        ), detail)
    return Headline("indeterminate", (
        f"Self-inflicted loss was {pct(f)} [{pct(lo)}, {pct(hi)}] of recall@10 misses in hybrid pipelines; "
        "the interval does not settle whether it is material."
    ), detail)


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def render(cells: Dict[Tuple[str, str], Dict[str, Any]], expected: Sequence[Tuple[str, str]]) -> str:
    missing = [key for key in expected if key not in cells]
    primary_missing = [key for key in missing if key[1] != "bm25_rerank"]
    beir_hybrid = [cells[(d, p)] for d in BEIR for p in HYBRID if (d, p) in cells]
    pooled_events = [event for cell in beir_hybrid for event in events_of(cell)]
    pooled = summarize(pooled_events) if pooled_events else None
    pooled_datasets = sorted({cell["dataset"] for cell in beir_hybrid}, key=BEIR.index)
    n_pooled_queries = len({event.query_id for event in pooled_events})
    comp = completeness(beir_hybrid)
    pooled_numbers = [PIPELINE_LABEL[p].split(" · ")[0] for p in HYBRID if any(c["pipeline"] == p for c in beir_hybrid)]
    pooled_label = f"**{' + '.join(pooled_numbers)} pooled**"

    out: List[str] = []
    w = out.append

    w("# Where multi-stage retrieval pipelines lose gold documents they had already found\n")
    if missing:
        names = ", ".join(f"`{d}__{p}`" for d, p in missing)
        w(
            f"> **Draft — {len(expected) - len(missing)} of {len(expected)} grid cells present.** Missing: {names}. "
            "Every figure below is computed on the cells present, and the pooled figures cover "
            f"{', '.join(pooled_datasets) or 'no dataset'} only. The headline is not the pre-registered result "
            "until the grid is complete; do not quote it.\n"
        )
        if any(key in RERANK_CELLS for key in missing):
            w(f"> Pipeline 4 and R cells are run on the build that carries the {RERANK_FIX_AMENDMENT} amendment "
              "(PREREGISTRATION.md): before it, the cross-encoder in config-built graphs scored empty text. Two "
              "pipeline 4 cells run before the fix were deleted and are re-run.\n")

    # 0. Headline
    w("## Finding\n")
    if pooled is not None:
        shares = {name: pooled.loss_share_by_class[name] for name in OPERATOR_CLASSES if name in pooled.loss_share_by_class}
        head = headline(pooled.self_inflicted_fraction, shares, n_pooled_queries, len(pooled_datasets), comp)
        prefix = "**Provisional:** " if primary_missing else ""
        w(f"{prefix}{head.sentence}\n")
        w(f"Branch: **{head.branch}** (PREREGISTRATION.md §2). {head.detail}\n")
    else:
        w("No hybrid-pipeline cell has run yet.\n")

    # 1. Question and definitions
    w("## 1. Questions and definitions\n")
    w(
        "The study asks where recall is lost inside multi-stage retrieval pipelines, using the lineage "
        "retobs records at every operator. The three primary questions, their statistics, and the "
        "expected directions were committed in [`PREREGISTRATION.md`](PREREGISTRATION.md) before any "
        "cell ran; everything else here is labelled exploratory.\n"
    )
    w(
        "- **Q1.** What fraction of recall@10 misses are *self-inflicted*: the gold document reached the "
        "top 10 at some operator's output and a later operator pushed it out?\n"
        "- **Q2.** Does adding a cross-encoder rerank stage change that fraction, and what does the "
        "reranker contribute to nDCG@10?\n"
        "- **Q3.** In the routed HotpotQA pipeline, which operator class carries the largest share of the "
        "loss, and how much of it is recovered later?\n"
    )
    w(
        f"For each (query, gold document) pair: **delivered** if it is in the final top {DELIVERY_K}; "
        "**destroyed** if it was inside the top 10 at some operator's output and is not delivered — the "
        "*destroying operator* is the last one that moved it from inside the window at its input to "
        "outside at its output; **surfaced, never in window** if some operator returned it but never in "
        "its top 10; **never surfaced** if no operator returned it (the retrieval ceiling). The "
        "**self-inflicted fraction** is destroyed ÷ all misses. **Loss share** of an operator class is its "
        "share of destroyed events. Full definitions: PREREGISTRATION.md §3.\n"
    )

    # 2. Grid and provenance
    w("## 2. Grid and provenance\n")
    rows = []
    for dataset, pipeline in expected:
        cell = cells.get((dataset, pipeline))
        if cell is None:
            rows.append([dataset, PIPELINE_LABEL[pipeline], "not run", "—", "—", "—", "—"])
            continue
        loss = cell["loss"]
        rows.append([
            dataset, PIPELINE_LABEL[pipeline], f"`{cell['run_id']}`", f"{cell['n_queries']:,}",
            f"{loss['n_pairs']:,}", pct(loss["completeness"]), f"`{cell['build']['git_sha']}`",
        ])
    w(table(["Dataset", "Pipeline", "Run", "Queries", "Gold pairs", "Lineage complete", "Build"], rows, "llrrrrl") + "\n")
    w(
        "BEIR test splits in full (nfcorpus, scifact, fiqa); no subsampling was needed. Dense encoder "
        "`sentence-transformers/all-MiniLM-L6-v2`; cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2`; "
        "both on CPU. Every Run was produced by the same executor as `retobs evaluate` into "
        "`results/study/results.db`; the per-cell JSON beside this file holds every statistic and every "
        f"(query, gold) event. Intervals: {BOOTSTRAP_RESAMPLES:,}-resample percentile cluster bootstrap over "
        f"queries, seed {BOOTSTRAP_SEED}. No latency figure is reported anywhere in this study.\n"
    )
    hot = cells.get(HOTPOT)
    if hot is not None:
        w(f"HotpotQA: the flagship-demo subset (12,654-paragraph corpus), {hot['n_queries']:,} questions, "
          "query manifest `hotpotqa_query_manifest.json`.\n")

    # 3. Headline tables
    w("## 3. Where the misses come from\n")
    w("Share of recall@10 misses by cause, per pipeline and dataset. The BM25 and dense pipelines have "
      "one operator, so nothing can be self-inflicted; they are the control rows and show the retrieval "
      "ceiling.\n")
    rows = []
    for pipeline in PIPELINES:
        for dataset in BEIR:
            cell = cells.get((dataset, pipeline))
            if cell is None:
                continue
            loss = cell["loss"]
            rows.append([
                PIPELINE_LABEL[pipeline], dataset,
                f"{loss['n_pairs'] - loss['outcome_counts']['delivered']:,}",
                pct_ci(rate_of(loss["self_inflicted_fraction"])),
                pct_ci(rate_of(loss["surfaced_never_in_window_fraction"])),
                pct_ci(rate_of(loss["never_surfaced_fraction"])),
            ])
    if pooled is not None:
        rows.append([
            pooled_label, ", ".join(pooled_datasets),
            f"{pooled.n_pairs - pooled.outcome_counts['delivered']:,}",
            f"**{pct_ci(pooled.self_inflicted_fraction)}**",
            pct_ci(pooled.surfaced_never_in_window_fraction),
            pct_ci(pooled.never_surfaced_fraction),
        ])
    w(table(["Pipeline", "Dataset", "Misses", "Self-inflicted", "Surfaced, never top 10", "Never surfaced"], rows, "llrrrr") + "\n")

    if pooled is not None:
        weights = []
        misses_total = pooled.n_pairs - pooled.outcome_counts["delivered"]
        for dataset in pooled_datasets:
            n = sum(1 for e in pooled_events if e.query_id.startswith(f"{dataset}:") and e.outcome != "delivered")
            weights.append(f"{dataset} {pct(n / misses_total if misses_total else None)}")
        w(f"The pooled row weights every (query, gold) pair equally, as pre-registered, so it follows the "
          f"datasets with the most graded golds: share of pooled misses — {'; '.join(weights)}. Read the "
          "per-dataset rows beside it.\n")

    w("**Loss share by operator class** (destroyed events only; classes with no event in any cell are "
      "omitted — filter/dedup, routing/merge, expand, and other have no operator in pipelines 3 and 4).\n")
    rows = []
    for pipeline in HYBRID:
        for dataset in BEIR:
            cell = cells.get((dataset, pipeline))
            if cell is None:
                continue
            shares = cell["loss"]["loss_share_by_class"]
            destroyed = cell["loss"]["outcome_counts"]["destroyed"]
            rows.append([PIPELINE_LABEL[pipeline], dataset, f"{destroyed:,}",
                         pct_ci(rate_of(shares["fusion"])), pct_ci(rate_of(shares["rerank"]))])
    if pooled is not None:
        rows.append([pooled_label, ", ".join(pooled_datasets), f"{pooled.outcome_counts['destroyed']:,}",
                     pct_ci(pooled.loss_share_by_class["fusion"]), pct_ci(pooled.loss_share_by_class["rerank"])])
    w(table(["Pipeline", "Dataset", "Destroyed", "Fusion", "Rerank"], rows, "llrrr") + "\n")

    w("**Fixed K = 50 variant** (PREREGISTRATION.md §3.1): the same misses, counting a gold as surfaced only "
      "where it appeared at rank ≤ 50. The self-inflicted fraction does not change by construction, so in "
      "pipelines 3 and 4 the two columns sum to 100% minus the self-inflicted share in the first table.\n")
    rows = []
    for pipeline in PIPELINES:
        for dataset in BEIR:
            cell = cells.get((dataset, pipeline))
            if cell is None:
                continue
            loss = cell["loss"]
            rows.append([PIPELINE_LABEL[pipeline], dataset,
                         pct_ci(rate_of(loss["surfaced_never_in_window_fraction_fixed_k"])),
                         pct_ci(rate_of(loss["never_surfaced_fraction_fixed_k"]))])
    w(table(["Pipeline", "Dataset", "Surfaced ≤ 50, never top 10", "Not surfaced within 50"], rows, "llrr") + "\n")

    # 4. Recovery
    w("## 4. Recovery\n")
    w("A recovery is a gold pushed out of the top 10 by one operator and moved back in by a later one. "
      "In pipelines 3 and 4 only the reranker can follow a displacing operator, and it sees only the "
      "fused list, so recoveries are possible only there.\n")
    rows = []
    for pipeline in HYBRID + ("hotpot_routed",):
        for dataset in BEIR + ("hotpotqa",):
            cell = cells.get((dataset, pipeline))
            if cell is None:
                continue
            loss = cell["loss"]
            rows.append([PIPELINE_LABEL[pipeline], dataset, f"{loss['displaced_pairs']:,}",
                         pct_ci(rate_of(loss["recovery_rate"])), pct_ci(rate_of(loss["redisplacement_rate"])),
                         f"{loss['destroyed_first_differs_from_last']:,}", f"{loss['set_refound_pairs']:,}"])
    w(table(["Pipeline", "Dataset", "Displaced pairs", "Recovered", "Re-displaced after recovery",
             "First ≠ last displacer", "Set-level re-finds (exploratory)"], rows, "llrrrrr") + "\n")

    # 5. Marginal contributions
    w("## 5. Marginal contributions by replay tier\n")
    w("Counterfactual replay removes one operator and replays the recorded lineage (strict rule: "
      "`indeterminate` whenever a later operator would have to rank documents it never saw). FUSE replays "
      "are EXACT (RRF is recomputed); RERANK replays are OBSERVED_ABLATION (the reranker's input order is "
      "passed through). Tiers are never averaged together. Sign-flip test, Benjamini-Hochberg q-values per "
      "pipeline.\n")
    rows = []
    caveats: Dict[str, str] = {}
    for pipeline in HYBRID + ("bm25_rerank", "hotpot_routed"):
        for dataset in BEIR + ("hotpotqa",):
            cell = cells.get((dataset, pipeline))
            if cell is None:
                continue
            by_op = {row["op_id"]: row for row in cell["marginal"]["recall"]}
            for row in cell["marginal"]["ndcg"]:
                rec = by_op.get(row["op_id"], {})
                status = row["result_status"]
                assumptions = row.get("assumptions") or {}
                strategy = assumptions.get("strategy", "—")
                if assumptions.get("caveats"):
                    caveats.setdefault(strategy, " ".join(assumptions["caveats"]))
                rows.append([
                    PIPELINE_LABEL[pipeline], dataset, f"`{row['op_id']}`", row["replay_policy"], f"`{strategy}`",
                    f"{signed(row['delta'])} [{signed(row['ci_low'])}, {signed(row['ci_high'])}]" if status == "replayed" else status,
                    f"{signed(rec.get('delta'))}" if rec.get("result_status") == "replayed" else rec.get("result_status", "—"),
                    num(row.get("q_value"), 4) if row.get("q_value") is not None else "—",
                    f"{row['n_pairs']:,}",
                ])
    w(table(["Pipeline", "Dataset", "Operator", "Tier", "Replay strategy", "Δ nDCG@10 [95% CI]", "Δ recall@10", "q", "Queries"],
            rows, "lllllrrrr") + "\n")
    w("A positive Δ means the pipeline scores higher *with* the operator than without it. What each replay "
      "strategy does, as recorded with the result:\n")
    w("\n".join(f"- `{name}`: {text}" for name, text in sorted(caveats.items())) + "\n")
    if any(row[4] == "`remove_outputs`" for row in rows):
        w("A fusion step that is not the last operator is replayed by `remove_outputs`, which removes only "
          "documents the fusion introduced itself. RRF introduces none, so its Δ there is zero by construction "
          "and says nothing about how much the fused order helped; the fused order's effect is measured where "
          "fusion is the final operator (pipeline 3).\n")

    w("**Final-stage quality** (context for the tables above; nDCG@10 with linear gain, 95% CI).\n")
    rows = []
    for dataset in BEIR:
        row = [dataset]
        for pipeline in PIPELINES:
            cell = cells.get((dataset, pipeline))
            if cell is None:
                row.append("—")
                continue
            m = final_metric(cell, "ndcg@10")
            row.append(f"{num(m['mean'])} [{num(m['ci_low'])}, {num(m['ci_high'])}]")
        rows.append(row)
    w(table(["Dataset"] + [PIPELINE_LABEL[p] for p in PIPELINES], rows) + "\n")

    # 6. Findings
    w("## 6. Findings\n")
    w("Primaries first, each beside its pre-registered expectation. A result against the expectation is "
      "reported in the same place and the same form as one that confirms it.\n")
    # Q1
    if pooled is not None:
        f = pooled.self_inflicted_fraction
        verdict = ("consistent with" if f.ci_low >= THRESHOLD else
                   "against" if f.ci_high < THRESHOLD else "not settled against")
        per = []
        for dataset in pooled_datasets:
            ev = [e for e in pooled_events if e.query_id.startswith(f"{dataset}:")]
            per.append(f"{dataset} {pct_ci(summarize(ev).self_inflicted_fraction)}")
        pooled_pipelines = sorted({cell["pipeline"] for cell in beir_hybrid}, key=HYBRID.index)
        which = " and ".join(PIPELINE_LABEL[p].split(" · ")[0] for p in pooled_pipelines)
        w(f"**Q1.** Pooled over pipeline{'s' if len(pooled_pipelines) > 1 else ''} {which} on "
          f"{', '.join(pooled_datasets)}, {pct_ci(f)} of recall@10 misses were self-inflicted "
          f"(per dataset: {'; '.join(per)}). *Expected: at least {pct(THRESHOLD, 0)}.* The result is "
          f"**{verdict}** the expectation. Depends on the {RERANK_FIX_AMENDMENT} amendment through pipeline 4.\n")
    else:
        w("**Q1.** Pending: no hybrid cell has run.\n")
    # Q2
    diffs = []
    pairs_a, pairs_b = [], []
    for dataset in BEIR:
        a, b = cells.get((dataset, "rrf_hybrid")), cells.get((dataset, "hybrid_rerank"))
        if a is None or b is None:
            continue
        ea, eb = events_of(a), events_of(b)
        pairs_a += ea
        pairs_b += eb
        diff, _ = self_inflicted_difference(ea, eb)
        rr = next(row for row in b["marginal"]["ndcg"] if row["op_id"] == "rerank")
        diffs.append((dataset, diff, rr))
    if diffs:
        pooled_diff, _ = self_inflicted_difference(pairs_a, pairs_b)
        per_diff = "; ".join(f"{d} {pp_ci(x)}" for d, x, _ in diffs)
        contrib = "; ".join(
            f"{d} {signed(r['delta'])} [{signed(r['ci_low'])}, {signed(r['ci_high'])}]" for d, _, r in diffs
        )
        helped = [d for d, _, r in diffs if r["result_status"] == "replayed" and r["ci_low"] > 0]
        hurt = [d for d, _, r in diffs if r["result_status"] == "replayed" and r["ci_high"] < 0]
        pooled_dir = detected(pooled_diff)
        rose = [d for d, x, _ in diffs if detected(x) == "up"]
        fell = [d for d, x, _ in diffs if detected(x) == "down"]
        flat = [d for d, x, _ in diffs if detected(x) is None]
        if pooled_dir == "up":
            parts = ["pooled, the self-inflicted fraction rose, as expected"]
        elif pooled_dir == "down":
            parts = ["pooled, the self-inflicted fraction **fell**, against the expectation"]
        else:
            parts = ["pooled, no change in the self-inflicted fraction was detected, against the expectation"]
        if rose:
            parts.append(f"it rose on {', '.join(rose)}")
        if fell:
            parts.append(f"it fell on {', '.join(fell)}")
        if flat:
            parts.append(f"no change was detected on {', '.join(flat)}")
        if helped:
            parts.append(f"the reranker raised nDCG@10 on {', '.join(helped)}, as expected")
        if hurt:
            parts.append(f"the reranker **lowered** nDCG@10 on {', '.join(hurt)}, against the expectation")
        w(f"**Q2.** Adding the cross-encoder changed the self-inflicted fraction by {pp_ci(pooled_diff)} pooled "
          f"({per_diff}). The reranker's marginal contribution to nDCG@10 (OBSERVED_ABLATION): {contrib}. "
          "*Expected: a positive marginal contribution and a higher self-inflicted fraction.* In words: "
          + "; ".join(parts) + ". A difference counts as detected only when its interval excludes 0 "
          f"(PREREGISTRATION.md §6). Depends on the {RERANK_FIX_AMENDMENT} amendment.\n")
    else:
        w("**Q2.** Pending: needs both hybrid pipelines on at least one dataset.\n")
    # Q3
    if hot is not None:
        shares = {k: rate_of(v) for k, v in hot["loss"]["loss_share_by_class"].items()}
        ranked = sorted(shares.items(), key=lambda item: -(item[1].value or 0.0))
        (top, top_rate), (runner, runner_rate) = ranked[0], ranked[1]
        sep = "overlaps" if overlaps(top_rate, runner_rate) else "does not overlap"
        w(f"**Q3.** In the routed HotpotQA pipeline the largest loss share is **{top}** at {pct_ci(top_rate)}; its "
          f"interval {sep} the runner-up ({runner}, {pct_ci(runner_rate)}). Recovery: "
          f"{pct_ci(rate_of(hot['loss']['recovery_rate']))} of displaced golds were moved back into the top 10; "
          f"{pct_ci(rate_of(hot['loss']['redisplacement_rate']))} of those were displaced again. *Expected: fusion "
          "largest, rerank second, fewer than half of displaced golds recovered.*\n")
    else:
        w("**Q3.** Pending: the HotpotQA routed cell has not run.\n")

    w("**Exploratory** (no pre-registered expectation; not headline material):\n")
    exploratory = []
    for dataset in BEIR:
        a, b = cells.get((dataset, "rrf_hybrid")), cells.get((dataset, "hybrid_rerank"))
        if a is None or b is None:
            continue
        fa, fb = final_metric(a, "ndcg@10"), final_metric(b, "ndcg@10")
        exploratory.append(f"- {dataset}: final nDCG@10 {num(fa['mean'])} with RRF alone and {num(fb['mean'])} "
                           "after the cross-encoder.")
    for dataset in BEIR:
        base = cells.get((dataset, "dense_only"))
        if base is None:
            continue
        exploratory.append(f"- {dataset}: the dense lane alone never surfaces "
                           f"{pct_ci(rate_of(base['loss']['never_surfaced_fraction']))} of its misses in the top 100.")
    w("\n".join(exploratory) + "\n" if exploratory else "None yet.\n")

    # 7. Reconciliation
    w("## 7. Reconciliation with the prior published claim\n")
    w(f"An earlier published summary of this project reported, for fiqa on build 0.1.0, nDCG@10 of "
      f"{PRIOR['bm25']:.3f} for BM25, {PRIOR['dense']:.3f} for dense, and {PRIOR['bm25_rerank']:.3f} for BM25 "
      f"followed by a cross-encoder (`results/BENCHMARK_ANALYSIS.md`), summarised as \"+"
      f"{100 * (PRIOR['dense'] / PRIOR['bm25'] - 1):.0f}% nDCG@10 over BM25\" together with a latency ratio. "
      "A ratio *reproduces* when the prior value lies inside the current build's 95% paired bootstrap "
      "interval for the same ratio (PREREGISTRATION.md §8). FiQA's relevance labels are binary, so the "
      "change from exponential to linear nDCG gain since that build does not affect these numbers.\n")
    fiqa = {p: cells.get(("fiqa", p)) for p in ("bm25_only", "dense_only", "hybrid_rerank", "bm25_rerank")}
    rows = []

    def reconcile(label: str, num_key: str, den_key: str, prior: Optional[float], note: str = "") -> None:
        a, b = fiqa[num_key], fiqa[den_key]
        prior_text = num(prior, 2) if prior is not None else "—"
        if a is None or b is None or "per_query" not in a or "per_query" not in b:
            rows.append([label, prior_text, "pending", "pending", note or "cell not run"])
            return
        value, low, high, n = ratio_of_means(a["per_query"]["ndcg@10"], b["per_query"]["ndcg@10"])
        if prior is None:
            status = "—"
        else:
            status = "REPRODUCED" if low <= prior <= high else "NOT REPRODUCED"
        rows.append([label, prior_text, f"{value:.2f} [{low:.2f}, {high:.2f}]", status, note or f"{n} paired queries"])

    reconcile("dense ÷ BM25", "dense_only", "bm25_only", PRIOR["dense"] / PRIOR["bm25"])
    reconcile("BM25 + rerank ÷ BM25", "bm25_rerank", "bm25_only", PRIOR["bm25_rerank"] / PRIOR["bm25"])
    reconcile("BM25 + rerank ÷ dense", "bm25_rerank", "dense_only", PRIOR["bm25_rerank"] / PRIOR["dense"])
    reconcile("hybrid + rerank ÷ dense", "hybrid_rerank", "dense_only", None,
              "different configuration from the prior rerank arm; shown, not reconciled")
    w(table(["nDCG@10 ratio on fiqa", "Prior", "Current build [95% CI]", "Status", "Note"], rows, "lrrll") + "\n")
    w("The latency half of the prior claim is **not measured** in this study (no latency figure is recorded "
      "in any study artifact) and cannot be reconciled here; it stands withdrawn unless re-measured "
      "separately with the machine named.\n")

    # 8. Limitations
    w("## 8. Limitations\n")
    lim = [
        "BEIR relevance labels are incomplete: an unlabelled document in the top 10 counts as a miss for the "
        "gold it displaced even if it is also relevant. Absolute fractions depend on how densely each "
        "dataset is labelled.",
        "Small encoders on CPU (MiniLM-L6 bi-encoder and cross-encoder). Larger models would move every "
        "ceiling and loss figure; the method, not the magnitudes, is what transfers.",
        "Single-seed grid. The intervals capture query sampling, not model or index variance.",
        "Pipelines 3 and 4 have one or two non-source operators, so their loss shares are close to "
        "tautological (fusion is the only possible destroyer in pipeline 3). The class comparison with real "
        "content is Q3.",
        "Replay tiers differ in strength: EXACT (fusion) replays recompute the operator's function; "
        "OBSERVED_ABLATION (rerank) replays pass the input order through and reuse recorded downstream "
        "scores.",
        "The pooled Q1 figure weights (query, gold) pairs equally and is therefore dominated by the dataset "
        "with the most graded golds per query; the per-dataset rows are the more informative view.",
        "HotpotQA uses the flagship-demo subset (a 12,654-paragraph corpus built from the 1,300 sampled "
        "questions' bundled paragraphs), not the full corpus, so its retrieval ceiling is far easier than "
        "full-corpus HotpotQA.",
    ]
    w("\n".join(f"- {item}" for item in lim) + "\n")

    # 9. Reproduce
    w("## 9. Reproduce\n")
    w("```bash\npython scripts/study_loss_attribution.py   # runs missing cells; finished cells are skipped\n"
      "python scripts/render_study.py            # rewrites this file from results/study/cells/\n```\n")
    w("Pre-registration and amendments: [`PREREGISTRATION.md`](PREREGISTRATION.md). The 2026-09-17 replay "
      "amendment affects only pipeline 5's marginal contributions. The "
      f"{RERANK_FIX_AMENDMENT} reranker-text amendment affects every pipeline 4 and R figure, and through them "
      "the pooled Q1 figure, Q2, and the rerank rows of §7.\n")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if STUDY.md differs from a fresh render")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    text = render(load_cells(), expected_cells())
    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(f"{out} is stale; run python scripts/render_study.py")
            return 1
        print(f"{out} is current")
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
