#!/usr/bin/env python3
"""Extract benchmark analytics from publish SQLite DBs (stdout JSON)."""
from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from retrieval_observatory.classifier.labels import to_training_class

DATASETS = [
    ("nfcorpus", ".retobs/publish_sweep_nfcorpus.db", "37d3a79c"),
    ("scifact", ".retobs/publish_sweep_scifact.db", "49b423cf"),
    ("fiqa", ".retobs/publish_sweep_fiqa.db", "0784ed30"),
    ("cohere_nfcorpus", ".retobs/publish_cohere_nfcorpus.db", "a6dad22f"),
]


def pct(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    i = (len(s) - 1) * p / 100
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (i - lo)


def mean(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def bootstrap_ci(values: List[float], n_boot: int = 5000, alpha: float = 0.05, seed: int = 42) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    random.seed(seed)
    if not values:
        return None, None, None
    if len(values) == 1:
        return values[0], values[0], values[0]
    boots = []
    n = len(values)
    for _ in range(n_boot):
        sample = [values[random.randint(0, n - 1)] for _ in range(n)]
        boots.append(mean(sample))  # type: ignore[arg-type]
    boots.sort()
    lo = boots[int(n_boot * alpha / 2)]
    hi = boots[int(n_boot * (1 - alpha / 2)) - 1]
    return mean(values), lo, hi


def ci_overlap(lo1: float, hi1: float, lo2: float, hi2: float) -> bool:
    return not (hi1 < lo2 or hi2 < lo1)


def paired_bootstrap_pvalue(a: List[float], b: List[float], n_boot: int = 10000, seed: int = 42) -> Optional[float]:
    """Two-sided p-value for mean(b-a) > 0 via paired bootstrap."""
    if len(a) != len(b) or len(a) < 2:
        return None
    random.seed(seed)
    diffs = [b[i] - a[i] for i in range(len(a))]
    obs = mean(diffs)
    if obs is None:
        return None
    n = len(diffs)
    count = 0
    for _ in range(n_boot):
        sample = [diffs[random.randint(0, n - 1)] for _ in range(n)]
        boot_mean = mean(sample)
        if boot_mean is not None and boot_mean >= obs:
            count += 1
        if boot_mean is not None and boot_mean <= -obs:
            count += 1
    return count / n_boot


def final_stage_index(cur: sqlite3.Cursor, run_id: str, pipeline_id: str) -> int:
    r = cur.execute(
        """
        SELECT MAX(stage_index) mx FROM metric_scores
        WHERE run_id=? AND pipeline_id=? AND stage_index >= 0
        """,
        (run_id, pipeline_id),
    ).fetchone()[0]
    return int(r) if r is not None else 0


def get_per_query_metrics(cur: sqlite3.Cursor, run_id: str, pipeline_id: str, stage_idx: int) -> Dict[str, Dict[str, float]]:
    rows = cur.execute(
        """
        SELECT query_id, metric_name, k, value FROM metric_scores
        WHERE run_id=? AND pipeline_id=? AND stage_index=?
        """,
        (run_id, pipeline_id, stage_idx),
    ).fetchall()
    per_q: Dict[str, Dict[str, float]] = defaultdict(dict)
    for qid, metric_name, k, value in rows:
        key = f"{metric_name}@{k}" if k else metric_name
        per_q[qid][key] = value
    return per_q


def pareto_frontier(points: List[Dict[str, Any]]) -> List[str]:
    """Maximize ndcg, minimize latency_p50."""
    frontier = []
    for p in points:
        dominated = False
        for q in points:
            if q["id"] == p["id"]:
                continue
            if q["ndcg10"] >= p["ndcg10"] and q["latency_p50"] <= p["latency_p50"]:
                if q["ndcg10"] > p["ndcg10"] or q["latency_p50"] < p["latency_p50"]:
                    dominated = True
                    break
        if not dominated:
            frontier.append(p["id"])
    return frontier


def analyze_dataset(ds_name: str, db_path: str, run_id: str) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    man_row = cur.execute("SELECT manifest_json FROM run_manifests WHERE run_id=?", (run_id,)).fetchone()
    manifest = json.loads(man_row[0]) if man_row else {}

    pipelines = [
        r[0]
        for r in cur.execute(
            "SELECT DISTINCT pipeline_id FROM metric_scores WHERE run_id=? ORDER BY pipeline_id",
            (run_id,),
        ).fetchall()
    ]

    ds_out: Dict[str, Any] = {"run_id": run_id, "db_path": db_path, "manifest": manifest, "pipelines": {}}

    pipe_points = []
    bm25_ndcg: Optional[List[float]] = None

    for pid in pipelines:
        si = final_stage_index(cur, run_id, pid)
        per_q = get_per_query_metrics(cur, run_id, pid, si)
        per_q0 = get_per_query_metrics(cur, run_id, pid, 0) if si > 0 else None

        qids = sorted(per_q.keys())
        ndcg = [per_q[q]["ndcg@10"] for q in qids if "ndcg@10" in per_q[q]]
        rec = [per_q[q]["recall@10"] for q in qids if "recall@10" in per_q[q]]
        mrr = [per_q[q]["mrr"] for q in qids if "mrr" in per_q[q]]

        lat_rows = cur.execute(
            """
            SELECT latency_ms FROM raw_results
            WHERE run_id=? AND pipeline_id=? AND stage_index=-1
            """,
            (run_id, pid),
        ).fetchall()
        lat = [r[0] for r in lat_rows]

        stage_lat = {}
        for st_idx, st_id, lat_ms in cur.execute(
            """
            SELECT stage_index, stage_id, latency_ms FROM raw_results
            WHERE run_id=? AND pipeline_id=? AND stage_index >= 0
            """,
            (run_id, pid),
        ):
            key = f"{st_idx}:{st_id}"
            stage_lat.setdefault(key, []).append(lat_ms)

        pout: Dict[str, Any] = {
            "final_stage_index": si,
            "n_queries_scored": len(per_q),
            "ndcg10_mean": mean(ndcg),
            "ndcg10_ci": bootstrap_ci(ndcg),
            "recall10_mean": mean(rec),
            "recall10_ci": bootstrap_ci(rec),
            "mrr_mean": mean(mrr),
            "mrr_ci": bootstrap_ci(mrr),
            "latency_p50": pct(lat, 50),
            "latency_p95": pct(lat, 95),
            "latency_mean": mean(lat),
            "stage_latency": {
                k: {"p50": pct(v, 50), "p95": pct(v, 95), "mean": mean(v), "n": len(v)}
                for k, v in stage_lat.items()
            },
            "quality_per_ms": (mean(ndcg) / mean(lat) * 1000) if mean(lat) and mean(ndcg) else None,
        }

        if pid == "bm25":
            bm25_ndcg = ndcg

        if per_q0 and si > 0:
            q0 = sorted(per_q0.keys())
            ndcg0 = [per_q0[q]["ndcg@10"] for q in q0 if "ndcg@10" in per_q0[q]]
            rec0 = [per_q0[q]["recall@10"] for q in q0 if "recall@10" in per_q0[q]]
            pout["stage0_ndcg10_mean"] = mean(ndcg0)
            pout["stage0_recall10_mean"] = mean(rec0)
            pout["rerank_delta"] = {
                "ndcg_abs": (mean(ndcg) or 0) - (mean(ndcg0) or 0),
                "recall_abs": (mean(rec) or 0) - (mean(rec0) or 0),
                "ndcg_rel_pct": 100 * ((mean(ndcg) or 0) - (mean(ndcg0) or 0)) / (mean(ndcg0) or 1e-9),
                "recall_rel_pct": 100 * ((mean(rec) or 0) - (mean(rec0) or 0)) / (mean(rec0) or 1e-9),
            }
            # recovery vs reorder: both improve = recovery
            pout["rerank_mode"] = (
                "recovery"
                if (pout["rerank_delta"]["recall_abs"] or 0) > 0.001 and (pout["rerank_delta"]["ndcg_abs"] or 0) > 0.001
                else "reordering"
                if (pout["rerank_delta"]["ndcg_abs"] or 0) > 0.001
                else "no_gain"
            )

        if bm25_ndcg and pid != "bm25" and len(ndcg) == len(bm25_ndcg):
            # align by query order
            paired_p = paired_bootstrap_pvalue(bm25_ndcg, ndcg)
            pout["vs_bm25_ndcg_pvalue"] = paired_p

        ds_out["pipelines"][pid] = pout
        pipe_points.append(
            {
                "id": pid,
                "ndcg10": pout["ndcg10_mean"],
                "latency_p50": pout["latency_p50"],
            }
        )

    ds_out["pareto_frontier"] = pareto_frontier([p for p in pipe_points if p["ndcg10"] is not None and p["latency_p50"] is not None])

    # Best / weakest by ndcg
    ranked = sorted(
        [(pid, ds_out["pipelines"][pid]["ndcg10_mean"]) for pid in pipelines],
        key=lambda x: x[1] or 0,
        reverse=True,
    )
    if ranked:
        best, worst = ranked[0], ranked[-1]
        b_m, w_m = best[1] or 0, worst[1] or 0
        ds_out["best_ndcg"] = {"pipeline": best[0], "mean": b_m}
        ds_out["weakest_ndcg"] = {"pipeline": worst[0], "mean": w_m}
        ds_out["ndcg_improvement_abs"] = b_m - w_m
        ds_out["ndcg_improvement_rel_pct"] = 100 * (b_m - w_m) / w_m if w_m else None

    # CI overlaps for ndcg
    overlaps = []
    for i, a in enumerate(pipelines):
        for b in pipelines[i + 1 :]:
            _, lo_a, hi_a = ds_out["pipelines"][a]["ndcg10_ci"]
            _, lo_b, hi_b = ds_out["pipelines"][b]["ndcg10_ci"]
            if lo_a is None or hi_a is None or lo_b is None or hi_b is None:
                continue
            overlaps.append(
                {
                    "a": a,
                    "b": b,
                    "overlap": ci_overlap(lo_a, hi_a, lo_b, hi_b),
                    "mean_a": ds_out["pipelines"][a]["ndcg10_mean"],
                    "mean_b": ds_out["pipelines"][b]["ndcg10_mean"],
                }
            )
    ds_out["ndcg_ci_overlaps"] = overlaps

    diag_pid = "bm25" if "bm25" in pipelines else pipelines[0]
    diags = cur.execute(
        """
        SELECT query_id, difficulty_bucket, failure_labels_json FROM query_diagnostics
        WHERE run_id=? AND pipeline_id=?
        """,
        (run_id, diag_pid),
    ).fetchall()

    bucket_recall: Dict[str, List[float]] = defaultdict(list)
    failure_counts: Dict[str, int] = defaultdict(int)
    actual_by_q: Dict[str, str] = {}
    for qid, bucket, labels_json in diags:
        actual_by_q[qid] = bucket
        si = final_stage_index(cur, run_id, diag_pid)
        r = cur.execute(
            """
            SELECT value FROM metric_scores
            WHERE run_id=? AND pipeline_id=? AND query_id=? AND stage_index=?
            AND metric_name='recall' AND k=10
            """,
            (run_id, diag_pid, qid, si),
        ).fetchone()
        if r:
            bucket_recall[bucket].append(r[0])
        for lab in json.loads(labels_json):
            failure_counts[lab] += 1

    ds_out["difficulty"] = {
        "pipeline_used": diag_pid,
        "bucket_counts": {b: len(v) for b, v in bucket_recall.items()},
        "bucket_recall10_mean": {b: mean(v) for b, v in bucket_recall.items()},
        "easy_hard_gap": (
            (mean(bucket_recall["easy"]) - mean(bucket_recall["hard"]))
            if "easy" in bucket_recall and "hard" in bucket_recall
            else None
        ),
    }
    ds_out["failure_labels"] = dict(sorted(failure_counts.items(), key=lambda x: -x[1]))

    pred_by_q: Dict[str, Dict] = {}
    for qid, meta_json in cur.execute(
        """
        SELECT query_id, query_metadata_json FROM metric_scores
        WHERE run_id=? AND query_metadata_json IS NOT NULL
        """,
        (run_id,),
    ):
        if qid in pred_by_q:
            continue
        meta = json.loads(meta_json)
        if "predicted_difficulty" in meta:
            pred_by_q[qid] = meta

    if pred_by_q:
        correct = 0
        total = 0
        brier_terms: List[float] = []
        pred_recall: Dict[str, List[float]] = defaultdict(list)
        for qid, meta in pred_by_q.items():
            pred = meta["predicted_difficulty"]
            proba = meta.get("predicted_difficulty_proba", {})
            actual = actual_by_q.get(qid)
            if actual:
                act_train = to_training_class(actual)
                if pred == act_train:
                    correct += 1
                total += 1
                classes = ["easy", "medium", "hard"]
                for c in classes:
                    y = 1.0 if c == act_train else 0.0
                    p = proba.get(c, 0.0)
                    brier_terms.append((p - y) ** 2)
            si = final_stage_index(cur, run_id, "bm25")
            rv = cur.execute(
                """
                SELECT value FROM metric_scores WHERE run_id=? AND pipeline_id='bm25'
                AND query_id=? AND stage_index=? AND metric_name='recall' AND k=10
                """,
                (run_id, qid, si),
            ).fetchone()
            if rv:
                pred_recall[pred].append(rv[0])

        ds_out["classifier"] = {
            "n_with_prediction": len(pred_by_q),
            "accuracy_vs_training_class": correct / total if total else None,
            "n_compared": total,
            "mean_brier_per_class_dim": mean(brier_terms),
            "pred_recall10_mean": {k: mean(v) for k, v in pred_recall.items()},
        }
    else:
        ds_out["classifier"] = None

    temp = cur.execute(
        "SELECT COUNT(*) FROM metric_scores WHERE run_id=? AND metric_name LIKE '%temporal%'",
        (run_id,),
    ).fetchone()[0]
    ds_out["has_temporal_metrics"] = temp > 0

    # cohere completion check
    for pid in pipelines:
        n_raw = cur.execute(
            "SELECT COUNT(*) FROM raw_results WHERE run_id=? AND pipeline_id=? AND stage_index=-1",
            (run_id, pid),
        ).fetchone()[0]
        ds_out["pipelines"][pid]["n_raw_pipeline_rows"] = n_raw

    conn.close()
    return ds_out


def main() -> None:
    out = {name: analyze_dataset(name, path, run_id) for name, path, run_id in DATASETS}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
