"""Query clustering for Production traffic segmentation.

Uses TF-IDF + agglomerative clustering on query text when scikit-learn is available
(semantic similarity without per-trace embedding storage). Falls back to
(difficulty × length bin) buckets when sklearn is missing or there are too few traces.
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


def _summarize_cluster(name: str, members: List[Dict[str, Any]], n_total: int) -> Dict[str, Any]:
    latencies = [float(m.get("total_latency_ms", 0.0)) for m in members]
    suspected = sum(1 for m in members if m.get("suspected_failures"))
    examples: List[str] = []
    for m in members:
        q = str(m.get("query_text", ""))
        if q and q not in examples:
            examples.append(q)
        if len(examples) >= 3:
            break
    return {
        "cluster": name,
        "size": len(members),
        "share": round(len(members) / n_total, 4),
        "examples": examples,
        "suspected_rate": round(suspected / len(members), 4),
        "latency_p50": round(_pct(latencies, 0.5), 1),
    }


def _heuristic_clusters(traces: List[Dict[str, Any]], n_total: int) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in traces:
        diff = t.get("predicted_difficulty") or "unknown"
        length = _length_bucket(len(str(t.get("query_text", "")).split()))
        groups[f"{diff} · {length}"].append(t)
    clusters = [_summarize_cluster(name, members, n_total) for name, members in groups.items()]
    clusters.sort(key=lambda c: -c["size"])
    return clusters


def _semantic_clusters(traces: List[Dict[str, Any]], n_total: int) -> List[Dict[str, Any]]:
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [str(t.get("query_text", "")).strip() or "(empty)" for t in traces]
    n_clusters = min(8, max(2, len(traces) // 5))
    vectorizer = TfidfVectorizer(max_features=500, ngram_range=(1, 2), min_df=1)
    matrix = vectorizer.fit_transform(texts)
    labels = AgglomerativeClustering(n_clusters=n_clusters, metric="cosine", linkage="average").fit_predict(
        matrix.toarray()
    )
    feature_names = vectorizer.get_feature_names_out()
    groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for trace, label in zip(traces, labels):
        groups[int(label)].append(trace)

    dense = matrix.toarray()
    clusters: List[Dict[str, Any]] = []
    for label, members in groups.items():
        indices = np.where(labels == label)[0]
        centroid = dense[indices].mean(axis=0)
        top_terms = [
            feature_names[idx]
            for idx in centroid.argsort()[-3:][::-1]
            if centroid[idx] > 0
        ]
        name = " · ".join(top_terms) if top_terms else f"semantic-{label}"
        clusters.append(_summarize_cluster(name, members, n_total))
    clusters.sort(key=lambda c: -c["size"])
    return clusters


def compute_clusters(traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not traces:
        return []
    n_total = len(traces)
    if n_total >= 5:
        try:
            return _semantic_clusters(traces, n_total)
        except ImportError:
            pass
        except Exception:
            pass
    return _heuristic_clusters(traces, n_total)
