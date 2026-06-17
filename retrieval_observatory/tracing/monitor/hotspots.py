"""Failure-hotspot detection.

Groups traces carrying suspected-failure signals by (difficulty × signal × pipeline) and
ranks the segments by volume and rate. Every hotspot is a *suspected* segment — it names the
proxy signal, never a measured-Recall claim.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List


def compute_hotspots(traces: List[Dict[str, Any]], top_n: int = 12) -> List[Dict[str, Any]]:
    # Denominator per difficulty, to express each hotspot as a share of comparable traffic.
    difficulty_totals: Counter = Counter()
    for t in traces:
        difficulty_totals[t.get("predicted_difficulty") or "unknown"] += 1

    seg_counts: Dict[tuple, int] = defaultdict(int)
    for t in traces:
        diff = t.get("predicted_difficulty") or "unknown"
        pipeline = t.get("pipeline_id") or "unknown"
        for label in t.get("suspected_failures") or []:
            seg_counts[(diff, label, pipeline)] += 1

    hotspots = []
    for (diff, label, pipeline), count in seg_counts.items():
        denom = difficulty_totals.get(diff, 0) or 1
        hotspots.append({
            "segment": f"{diff} · {label} · {pipeline}",
            "difficulty": diff,
            "label": label,
            "pipeline": pipeline,
            "count": count,
            "rate": round(count / denom, 4),
        })

    hotspots.sort(key=lambda h: (-h["count"], -h["rate"]))
    return hotspots[:top_n]
