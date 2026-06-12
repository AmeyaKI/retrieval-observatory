"""Aggregations over stored trace rows (the dicts returned by ``store.list_traces``).

These never compute Recall/NDCG — production has no ground truth. They summarize observable
quantities (status, latency, predicted difficulty, label-free suspected-failure signals).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

_LENGTH_BINS = [(0, 5), (6, 10), (11, 20), (21, 40), (41, 10_000)]


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _length_bin(tokens: int) -> str:
    for lo, hi in _LENGTH_BINS:
        if lo <= tokens <= hi:
            return f"{lo}-{hi}" if hi < 10_000 else f"{lo}+"
    return "?"


def summarize(traces: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline KPIs for a service+window."""
    n = len(traces)
    if n == 0:
        return {
            "trace_count": 0, "ok_rate": 0.0, "error_rate": 0.0,
            "latency_p50": 0.0, "latency_p95": 0.0, "suspected_failure_rate": 0.0,
        }
    latencies = [float(t.get("total_latency_ms", 0.0)) for t in traces]
    errors = sum(1 for t in traces if t.get("status") == "ERROR")
    oks = sum(1 for t in traces if t.get("status") == "OK")
    suspected = sum(1 for t in traces if t.get("suspected_failures"))
    return {
        "trace_count": n,
        "ok_rate": round(oks / n, 4),
        "error_rate": round(errors / n, 4),
        "latency_p50": round(_percentile(latencies, 0.5), 2),
        "latency_p95": round(_percentile(latencies, 0.95), 2),
        "suspected_failure_rate": round(suspected / n, 4),
    }


def compute_distribution(traces: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Binned distributions for the Distribution view."""
    difficulty = Counter()
    status = Counter()
    length = Counter()
    failure_labels = Counter()
    candidate_counts: List[int] = []
    latencies = [float(t.get("total_latency_ms", 0.0)) for t in traces]

    for t in traces:
        difficulty[t.get("predicted_difficulty") or "unknown"] += 1
        status[t.get("status") or "unknown"] += 1
        n_tokens = len(str(t.get("query_text", "")).split())
        length[_length_bin(n_tokens)] += 1
        for lbl in t.get("suspected_failures") or []:
            failure_labels[lbl] += 1

    return {
        "n": len(traces),
        "by_difficulty": dict(difficulty),
        "by_status": dict(status),
        "by_length_bin": dict(length),
        "by_failure_label": dict(failure_labels),
        "latency_percentiles": {
            "p50": round(_percentile(latencies, 0.5), 2),
            "p90": round(_percentile(latencies, 0.9), 2),
            "p95": round(_percentile(latencies, 0.95), 2),
            "p99": round(_percentile(latencies, 0.99), 2),
        },
    }
