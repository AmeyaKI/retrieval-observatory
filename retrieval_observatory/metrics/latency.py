from __future__ import annotations

from typing import Dict, List

import numpy as np


def latency_percentiles(
    latencies_ms: List[float],
    percentiles: List[int] = [50, 95, 99],
) -> Dict[str, float]:
    """Compute latency percentiles. Returns {p50: ..., p95: ..., p99: ...}."""
    if not latencies_ms:
        return {f"p{p}": 0.0 for p in percentiles}
    arr = np.array(latencies_ms, dtype=float)
    return {f"p{p}": float(np.percentile(arr, p)) for p in percentiles}


def per_stage_latency_percentiles(
    stage_latencies: Dict[int, List[float]],
    percentiles: List[int] = [50, 95, 99],
) -> Dict[int, Dict[str, float]]:
    """Compute latency percentiles per stage index."""
    return {
        stage_idx: latency_percentiles(lats, percentiles)
        for stage_idx, lats in stage_latencies.items()
    }
