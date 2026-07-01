"""Verify that compute_from_traces produces identical metrics to compute_and_store
for linear (non-branching) pipelines."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Set

import pytest

from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.tracing.lift import lift_pipeline_result
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


# ---------------------------------------------------------------------------
# Minimal in-memory store that captures metric rows
# ---------------------------------------------------------------------------
class _MemStore:
    def __init__(self):
        self.rows: List[Dict] = []

    async def save_metrics_batch(self, rows: List[Dict]) -> None:
        self.rows.extend(rows)

    async def save_metric(self, **kwargs) -> None:
        self.rows.append(kwargs)

    async def get_metrics(self, run_id: str) -> List[Dict]:
        return [r for r in self.rows if r.get("run_id") == run_id]

    async def get_results(self, run_id: str) -> list:
        return []

    async def get_run_status_counts(self, run_id: str) -> Dict[str, int]:
        return {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_docs(*ids: str) -> List[Document]:
    return [
        Document(id=doc_id, text="", score=1.0 / (i + 1), rank=i + 1)
        for i, doc_id in enumerate(ids)
    ]


def _make_result(query_id: str, pipeline_id: str) -> PipelineResult:
    """Two-stage pipeline: stage-0 retrieves 5 docs, stage-1 reranks to top 3."""
    stage0_docs = _make_docs("d1", "d2", "d3", "d4", "d5")
    stage1_docs = _make_docs("d3", "d1", "d5")
    return PipelineResult(
        query_id=query_id,
        pipeline_id=pipeline_id,
        snapshots=[
            StageSnapshot(
                stage_index=0,
                stage_id="bm25",
                documents=stage0_docs,
                latency_ms=12.0,
                candidate_count=5,
            ),
            StageSnapshot(
                stage_index=1,
                stage_id="reranker",
                documents=stage1_docs,
                latency_ms=8.0,
                candidate_count=3,
            ),
        ],
        total_latency_ms=20.0,
        status="OK",
    )


QRELS: Dict[str, Set[str]] = {
    "q1": {"d1", "d3", "d7"},
    "q2": {"d1", "d3", "d7"},
}


def _group_metrics(rows: List[Dict]) -> Dict[tuple, float]:
    """Group metric rows by (query_id, stage_index, metric_name, k) -> value."""
    grouped: Dict[tuple, float] = {}
    for r in rows:
        key = (r.get("query_id"), r.get("stage_index"), r.get("metric_name"), r.get("k"))
        grouped[key] = r.get("value", 0.0)
    return grouped


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metric_parity():
    engine = MetricsEngine(
        recall_at_k_values=[1, 5, 10],
        precision_at_k_values=[5],
        ndcg_at_k_values=[10],
        compute_mrr=True,
        compute_map=True,
    )
    results = [_make_result("q1", "pipe_a"), _make_result("q2", "pipe_a")]

    # --- Old path: compute_and_store ---
    old_store = _MemStore()
    await engine.compute_and_store("run1", old_store, results, QRELS)

    # --- New path: lift → compute_from_traces ---
    traces = [lift_pipeline_result(r, run_id="run1") for r in results]
    new_store = _MemStore()
    await engine.compute_from_traces("run1", new_store, traces, QRELS)

    old_metrics = _group_metrics(old_store.rows)
    new_metrics = _group_metrics(new_store.rows)

    quality_names = {"recall", "precision", "ndcg", "mrr", "map"}
    old_quality = {k: v for k, v in old_metrics.items() if k[2] in quality_names}
    new_quality = {k: v for k, v in new_metrics.items() if k[2] in quality_names}

    assert old_quality, "Old path produced no quality metrics"
    assert new_quality, "New path produced no quality metrics"
    assert set(old_quality.keys()) == set(new_quality.keys()), (
        f"Metric keys differ:\n  old-only: {set(old_quality) - set(new_quality)}\n"
        f"  new-only: {set(new_quality) - set(old_quality)}"
    )
    for key in sorted(old_quality):
        assert old_quality[key] == pytest.approx(new_quality[key], abs=1e-12), (
            f"Mismatch on {key}: old={old_quality[key]}, new={new_quality[key]}"
        )

    # Latency rows should also match per-stage
    old_latency = {k: v for k, v in old_metrics.items() if k[2] == "latency_ms"}
    new_latency = {k: v for k, v in new_metrics.items() if k[2] == "latency_ms"}
    assert set(old_latency.keys()) == set(new_latency.keys())
    for key in sorted(old_latency):
        assert old_latency[key] == pytest.approx(new_latency[key], abs=1e-9)
