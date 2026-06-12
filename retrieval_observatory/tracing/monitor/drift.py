"""Two-window drift detection over trace rows.

Compares a baseline window against a recent window on cheap, always-available features.
Categorical/binned features use PSI (Population Stability Index); the continuous latency
feature uses a two-sample Kolmogorov–Smirnov test. Every finding carries its evidence
(both distributions + the statistic) so the flag is explainable.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List

_PSI_MODERATE = 0.1
_PSI_SIGNIFICANT = 0.25
_KS_ALPHA = 0.05
_LENGTH_BINS = [(0, 5), (6, 10), (11, 20), (21, 40), (41, 10_000)]


def _length_bin(tokens: int) -> str:
    for lo, hi in _LENGTH_BINS:
        if lo <= tokens <= hi:
            return f"{lo}-{hi}" if hi < 10_000 else f"{lo}+"
    return "?"


def _categorical(traces: List[Dict[str, Any]], extractor) -> Counter:
    c: Counter = Counter()
    for t in traces:
        c[extractor(t)] += 1
    return c


def _psi(baseline: Counter, recent: Counter) -> float:
    keys = set(baseline) | set(recent)
    b_total = sum(baseline.values()) or 1
    r_total = sum(recent.values()) or 1
    psi = 0.0
    eps = 1e-6
    for k in keys:
        b = baseline.get(k, 0) / b_total
        r = recent.get(k, 0) / r_total
        b = max(b, eps)
        r = max(r, eps)
        psi += (r - b) * math.log(r / b)
    return psi


def _normalize(counter: Counter) -> Dict[str, float]:
    total = sum(counter.values()) or 1
    return {k: round(v / total, 4) for k, v in counter.items()}


def _ks_statistic(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = sorted(a), sorted(b)
    all_vals = sorted(set(sa) | set(sb))

    def cdf(s: List[float], x: float) -> float:
        # fraction of values <= x
        import bisect
        return bisect.bisect_right(s, x) / len(s)

    return max(abs(cdf(sa, x) - cdf(sb, x)) for x in all_vals)


def _ks_critical(n1: int, n2: int, alpha: float = _KS_ALPHA) -> float:
    if n1 == 0 or n2 == 0:
        return 1.0
    c_alpha = math.sqrt(-0.5 * math.log(alpha / 2))
    return c_alpha * math.sqrt((n1 + n2) / (n1 * n2))


_CAT_FEATURES = {
    "predicted_difficulty": lambda t: t.get("predicted_difficulty") or "unknown",
    "status": lambda t: t.get("status") or "unknown",
    "query_length_bin": lambda t: _length_bin(len(str(t.get("query_text", "")).split())),
}


def compute_drift(baseline: List[Dict[str, Any]], recent: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    # Categorical / binned features → PSI
    for feature, extractor in _CAT_FEATURES.items():
        b = _categorical(baseline, extractor)
        r = _categorical(recent, extractor)
        psi = _psi(b, r)
        severity = "none"
        if psi >= _PSI_SIGNIFICANT:
            severity = "significant"
        elif psi >= _PSI_MODERATE:
            severity = "moderate"
        findings.append({
            "feature": feature,
            "method": "PSI",
            "statistic": round(psi, 4),
            "drifted": psi >= _PSI_MODERATE,
            "severity": severity,
            "baseline": _normalize(b),
            "recent": _normalize(r),
        })

    # Suspected-failure rate → PSI on failed/ok split
    def failed(t):
        return "suspected" if t.get("suspected_failures") else "clean"
    b = _categorical(baseline, failed)
    r = _categorical(recent, failed)
    psi = _psi(b, r)
    findings.append({
        "feature": "suspected_failure_rate",
        "method": "PSI",
        "statistic": round(psi, 4),
        "drifted": psi >= _PSI_MODERATE,
        "severity": "significant" if psi >= _PSI_SIGNIFICANT else ("moderate" if psi >= _PSI_MODERATE else "none"),
        "baseline": _normalize(b),
        "recent": _normalize(r),
    })

    # Continuous latency → KS
    b_lat = [float(t.get("total_latency_ms", 0.0)) for t in baseline]
    r_lat = [float(t.get("total_latency_ms", 0.0)) for t in recent]
    ks = _ks_statistic(b_lat, r_lat)
    crit = _ks_critical(len(b_lat), len(r_lat))
    findings.append({
        "feature": "latency_ms",
        "method": "KS",
        "statistic": round(ks, 4),
        "drifted": ks > crit,
        "severity": "significant" if ks > crit else "none",
        "baseline": {"p50": round(_pct(b_lat, 0.5), 1), "p95": round(_pct(b_lat, 0.95), 1)},
        "recent": {"p50": round(_pct(r_lat, 0.5), 1), "p95": round(_pct(r_lat, 0.95), 1)},
    })

    # Rank: drifted first, then by statistic.
    findings.sort(key=lambda f: (not f["drifted"], -f["statistic"]))
    return findings


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
