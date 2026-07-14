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
    seg_trace_ids: Dict[tuple, List[str]] = defaultdict(list)
    for t in traces:
        diff = t.get("predicted_difficulty") or "unknown"
        pipeline = t.get("pipeline_id") or "unknown"
        for label in t.get("suspected_failures") or []:
            key = (diff, label, pipeline)
            seg_counts[key] += 1
            if t.get("trace_id") and len(seg_trace_ids[key]) < 50:
                seg_trace_ids[key].append(str(t["trace_id"]))

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
            "evidence_class": "heuristic",
            "method": "label_free_proxy_segment_count_v1",
            "sample_size": len(traces),
            "denominator": denom,
            "baseline": "selected_window_difficulty_traffic",
            "threshold": None,
            "supporting_trace_ids": seg_trace_ids[(diff, label, pipeline)],
        })

    hotspots.sort(key=lambda h: (-h["count"], -h["rate"]))
    return hotspots[:top_n]
