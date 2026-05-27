from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Union

import numpy as np

from retrieval_observatory.metrics.latency import latency_percentiles
from retrieval_observatory.metrics.ranking import dedupe_preserve_rank, map_score, mrr, ndcg_at_k, ndcg_at_k_graded
from retrieval_observatory.metrics.recall import recall_at_k, temporal_recall_at_k, temporal_recall_at_k_with_corpus
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
        qrels: Union[Dict[str, Set[str]], Dict[str, Dict[str, int]]],
        queries_by_id: Optional[Dict] = None,
        corpus_documents: Optional[Dict] = None,
    ) -> None:
        """Compute per-query metrics and write each row to metric_scores.

        qrels may be binary {query_id: {doc_id}} or graded {query_id: {doc_id: grade}}.
        Graded qrels use ndcg_at_k_graded for NDCG; binary metrics (Recall/MAP/MRR)
        treat any doc with grade > 0 as relevant.
        """
        # Detect format from first entry
        _sample = next(iter(qrels.values()), None)
        _graded = isinstance(_sample, dict)

        for result in results:
            if result.status != "OK":
                continue
            raw_qrel = qrels.get(result.query_id)
            if not raw_qrel:
                continue
            query = queries_by_id.get(result.query_id) if queries_by_id else None

            # relevant_set is always Set[str] with grade > 0, used by binary metrics
            if _graded:
                relevant_set: Set[str] = {
                    doc_id for doc_id, grade in raw_qrel.items() if grade > 0  # type: ignore[union-attr]
                }
                graded_qrel: Dict[str, int] = raw_qrel  # type: ignore[assignment]
            else:
                relevant_set = raw_qrel  # type: ignore[assignment]
                graded_qrel = {}

            if not relevant_set:
                continue

            # Query metadata to attach to every saved metric row for per-segment analysis
            query_meta = query.metadata if query else {}

            # For multi-stage pipelines, store end-to-end latency as stage_index=-1 so
            # percentiles are computed on the actual joint distribution, not summed per-stage.
            if len(result.snapshots) > 1:
                await self._save_metrics(
                    store,
                    [
                        {
                            "run_id": run_id,
                            "pipeline_id": result.pipeline_id,
                            "query_id": result.query_id,
                            "stage_index": -1,
                            "metric_name": "latency_ms",
                            "k": 0,
                            "value": result.total_latency_ms,
                            "query_metadata_json": query_meta,
                        }
                    ],
                )

            for snap in result.snapshots:
                doc_ids = dedupe_preserve_rank([d.id for d in snap.documents])
                metric_rows: List[Dict[str, Any]] = []

                # Recall@K (binary: grade > 0 = relevant)
                for k in self.recall_k:
                    score = recall_at_k(doc_ids, relevant_set, k)
                    metric_rows.append(
                        self._metric_row(
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            snap.stage_index,
                            "recall",
                            k,
                            score,
                            query_meta,
                        )
                    )

                # NDCG@K — graded when grade data is available, binary otherwise
                for k in self.ndcg_k:
                    if _graded:
                        score = ndcg_at_k_graded(doc_ids, graded_qrel, k)
                    else:
                        score = ndcg_at_k(doc_ids, relevant_set, k)
                    metric_rows.append(
                        self._metric_row(
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            snap.stage_index,
                            "ndcg",
                            k,
                            score,
                            query_meta,
                        )
                    )

                # MRR (k=0 sentinel)
                if self.compute_mrr:
                    score = mrr([doc_ids], [relevant_set])
                    metric_rows.append(
                        self._metric_row(
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            snap.stage_index,
                            "mrr",
                            0,
                            score,
                            query_meta,
                        )
                    )

                # MAP (k=0 sentinel)
                if self.compute_map:
                    from retrieval_observatory.metrics.ranking import average_precision
                    score = average_precision(doc_ids, relevant_set)
                    metric_rows.append(
                        self._metric_row(
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            snap.stage_index,
                            "map",
                            0,
                            score,
                            query_meta,
                        )
                    )

                # Temporal Recall@K
                if self.temporal_k and query and query.temporal_anchor:
                    for k in self.temporal_k:
                        score = temporal_recall_at_k(
                            snap.documents, relevant_set, k, query.temporal_anchor
                        )
                        if corpus_documents:
                            score = temporal_recall_at_k_with_corpus(
                                snap.documents,
                                relevant_set,
                                k,
                                query.temporal_anchor,
                                corpus_documents,
                            )
                        metric_rows.append(
                            self._metric_row(
                                run_id,
                                result.pipeline_id,
                                result.query_id,
                                snap.stage_index,
                                "temporal_recall",
                                k,
                                score,
                                query_meta,
                            )
                        )

                # Latency — store raw ms once; percentiles computed at aggregate time
                metric_rows.append(
                    self._metric_row(
                        run_id,
                        result.pipeline_id,
                        result.query_id,
                        snap.stage_index,
                        "latency_ms",
                        0,
                        snap.latency_ms,
                        query_meta,
                    )
                )
                for profile_name, profile_value in snap.profiling.items():
                    metric_rows.append(
                        self._metric_row(
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            snap.stage_index,
                            f"profile_{profile_name}",
                            0,
                            float(profile_value),
                            query_meta,
                        )
                    )
                await self._save_metrics(store, metric_rows)

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

            if metric_name == "latency_ms":
                # Expand into per-percentile entries; no bootstrap CI (not meaningful here)
                for p in self.latency_percentiles:
                    pct_value = float(np.percentile(arr, p))
                    pct_key = f"{pipeline_id}|stage{stage_index}|latency_p{p}@0"
                    aggregated[pct_key] = {
                        "pipeline_id": pipeline_id,
                        "stage_index": stage_index,
                        "metric_name": f"latency_p{p}",
                        "k": 0,
                        "mean": pct_value,
                        "std": 0.0,
                        "ci_low": pct_value,
                        "ci_high": pct_value,
                        "n": len(scores),
                        "zero_count": 0,
                        "zero_pct": 0.0,
                    }
                continue

            ci_low, ci_high = bootstrap_ci(scores, n_resamples=n_bootstrap)
            zero_count = int(np.sum(arr == 0.0))
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
                "zero_count": zero_count,
                "zero_pct": round(zero_count / len(scores) * 100, 1),
            }

        results = await store.get_results(run_id)
        by_pipeline: Dict[str, List[PipelineResult]] = defaultdict(list)
        for result in results:
            by_pipeline[result.pipeline_id].append(result)
        for pipeline_id, pipeline_results in by_pipeline.items():
            total = len(pipeline_results)
            if total == 0:
                continue
            timeout_count = sum(1 for r in pipeline_results if r.status == "TIMEOUT")
            error_count = sum(1 for r in pipeline_results if r.status == "ERROR")
            dropout_count = timeout_count + error_count
            for metric_name, value in (
                ("failure_rate", dropout_count / total),
                ("timeout_rate", timeout_count / total),
                ("dropout_count", float(dropout_count)),
            ):
                key = f"{pipeline_id}|stage-1|{metric_name}@0"
                aggregated[key] = {
                    "pipeline_id": pipeline_id,
                    "stage_index": -1,
                    "metric_name": metric_name,
                    "k": 0,
                    "mean": float(value),
                    "std": 0.0,
                    "ci_low": float(value),
                    "ci_high": float(value),
                    "n": total,
                    "zero_count": 0,
                    "zero_pct": 0.0,
                }

        return aggregated

    @staticmethod
    def _metric_row(
        run_id: str,
        pipeline_id: str,
        query_id: str,
        stage_index: int,
        metric_name: str,
        k: int,
        value: float,
        query_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "query_id": query_id,
            "stage_index": stage_index,
            "metric_name": metric_name,
            "k": k,
            "value": value,
            "query_metadata_json": query_metadata,
        }

    @staticmethod
    async def _save_metrics(store: BaseStore, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        if hasattr(store, "save_metrics_batch"):
            await store.save_metrics_batch(rows)
            return
        for row in rows:
            await store.save_metric(
                row["run_id"],
                row["pipeline_id"],
                row["query_id"],
                row["stage_index"],
                row["metric_name"],
                row["k"],
                row["value"],
                row["query_metadata_json"],
            )
