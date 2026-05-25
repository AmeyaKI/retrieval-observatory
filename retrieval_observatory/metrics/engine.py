from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

import numpy as np

from retrieval_observatory.metrics.latency import latency_percentiles
from retrieval_observatory.metrics.ranking import map_score, mrr, ndcg_at_k
from retrieval_observatory.metrics.recall import recall_at_k, temporal_recall_at_k
from retrieval_observatory.metrics.significance import bootstrap_ci
from retrieval_observatory.store.base import BaseStore
from retrieval_observatory.types import PipelineResult


class MetricsEngine:
    """Computes and stores per-query metrics; aggregation is always a GROUP BY query."""

    def __init__(
        self,
        recall_at_k_values: List[int] = [1, 5, 10],
        ndcg_at_k_values: List[int] = [10],
        temporal_recall_at_k_values: List[int] = [],
        latency_percentile_values: List[int] = [50, 95, 99],
        compute_mrr: bool = True,
        compute_map: bool = True,
    ):
        self.recall_k = recall_at_k_values
        self.ndcg_k = ndcg_at_k_values
        self.temporal_k = temporal_recall_at_k_values
        self.latency_percentiles = latency_percentile_values
        self.compute_mrr = compute_mrr
        self.compute_map = compute_map

    async def compute_and_store(
        self,
        run_id: str,
        store: BaseStore,
        results: List[PipelineResult],
        qrels: Dict[str, Set[str]],
        queries_by_id: Optional[Dict] = None,
    ) -> None:
        """Compute per-query metrics and write each row to metric_scores."""
        for result in results:
            if result.status != "OK":
                continue
            relevant = qrels.get(result.query_id, set())
            if not relevant:
                continue
            query = queries_by_id.get(result.query_id) if queries_by_id else None

            for snap in result.snapshots:
                doc_ids = [d.id for d in snap.documents]

                # Recall@K
                for k in self.recall_k:
                    score = recall_at_k(doc_ids, relevant, k)
                    await store.save_metric(
                        run_id, result.pipeline_id, result.query_id,
                        snap.stage_index, "recall", k, score,
                    )

                # NDCG@K
                for k in self.ndcg_k:
                    score = ndcg_at_k(doc_ids, relevant, k)
                    await store.save_metric(
                        run_id, result.pipeline_id, result.query_id,
                        snap.stage_index, "ndcg", k, score,
                    )

                # MRR (k=0 sentinel)
                if self.compute_mrr:
                    score = mrr([doc_ids], [relevant])
                    await store.save_metric(
                        run_id, result.pipeline_id, result.query_id,
                        snap.stage_index, "mrr", 0, score,
                    )

                # MAP (k=0 sentinel)
                if self.compute_map:
                    from retrieval_observatory.metrics.ranking import average_precision
                    score = average_precision(doc_ids, relevant)
                    await store.save_metric(
                        run_id, result.pipeline_id, result.query_id,
                        snap.stage_index, "map", 0, score,
                    )

                # Temporal Recall@K
                if self.temporal_k and query and query.temporal_anchor:
                    for k in self.temporal_k:
                        score = temporal_recall_at_k(
                            snap.documents, relevant, k, query.temporal_anchor
                        )
                        await store.save_metric(
                            run_id, result.pipeline_id, result.query_id,
                            snap.stage_index, "temporal_recall", k, score,
                        )

                # Latency — stored as a metric row per percentile
                lats = [snap.latency_ms]
                for p in self.latency_percentiles:
                    await store.save_metric(
                        run_id, result.pipeline_id, result.query_id,
                        snap.stage_index, f"latency_p{p}", 0, snap.latency_ms,
                    )

    async def aggregate(
        self,
        run_id: str,
        store: BaseStore,
        n_bootstrap: int = 1000,
    ) -> Dict[str, Any]:
        """Return aggregated metrics: mean ± std + 95% CI, grouped by pipeline/stage/metric/k."""
        raw_metrics = await store.get_metrics(run_id)

        # Group scores
        groups: Dict[tuple, List[float]] = defaultdict(list)
        for row in raw_metrics:
            key = (row["pipeline_id"], row["stage_index"], row["metric_name"], row["k"])
            groups[key].append(row["value"])

        aggregated: Dict[str, Any] = {}
        for (pipeline_id, stage_index, metric_name, k), scores in groups.items():
            arr = np.array(scores)
            ci_low, ci_high = bootstrap_ci(scores, n_resamples=n_bootstrap)
            key = f"{pipeline_id}|stage{stage_index}|{metric_name}@{k}"
            aggregated[key] = {
                "pipeline_id": pipeline_id,
                "stage_index": stage_index,
                "metric_name": metric_name,
                "k": k,
                "mean": float(arr.mean()),
                "std": float(arr.std()),
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n": len(scores),
            }

        return aggregated
