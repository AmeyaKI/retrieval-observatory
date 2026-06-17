"""Heuristic query clustering for traffic segmentation.

MVP clustering buckets traffic by (predicted difficulty × query-length bin). This is
dependency-free and explainable. Embedding-based semantic clustering is deferred (it would
require storing per-trace vectors and a transformer dependency).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

_LENGTH_BINS = [(0, 5), (6, 20), (21, 10_000)]
_LENGTH_LABEL = {0: "short", 6: "medium", 21: "long"}


def _length_bucket(tokens: int) -> str:
    for lo, hi in _LENGTH_BINS:
        if lo <= tokens <= hi:
            return _LENGTH_LABEL[lo]
    return "short"


def _pct(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def compute_clusters(traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    n_total = len(traces) or 1
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in traces:
        diff = t.get("predicted_difficulty") or "unknown"
        length = _length_bucket(len(str(t.get("query_text", "")).split()))
        groups[f"{diff} · {length}"].append(t)

    clusters = []
    for name, members in groups.items():
        latencies = [float(m.get("total_latency_ms", 0.0)) for m in members]
        suspected = sum(1 for m in members if m.get("suspected_failures"))
        examples: List[str] = []
        for m in members:
            q = str(m.get("query_text", ""))
            if q and q not in examples:
                examples.append(q)
            if len(examples) >= 3:
                break
        clusters.append({
            "cluster": name,
            "size": len(members),
            "share": round(len(members) / n_total, 4),
            "examples": examples,
            "suspected_rate": round(suspected / len(members), 4),
            "latency_p50": round(_pct(latencies, 0.5), 1),
        })

    clusters.sort(key=lambda c: -c["size"])
    return clusters
