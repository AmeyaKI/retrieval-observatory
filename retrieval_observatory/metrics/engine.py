from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Union

from retrieval_observatory.metrics.ranking import (
    dedupe_preserve_rank,
    mrr,
    ndcg_at_k,
    ndcg_at_k_graded,
    precision_at_k,
)
from retrieval_observatory.metrics.recall import recall_at_k, temporal_recall_at_k, temporal_recall_at_k_with_corpus
from retrieval_observatory.metrics.significance import bootstrap_ci
from retrieval_observatory.store.base import BaseStore


def _mean(values: List[float]) -> float:
    return sum(float(value) for value in values) / len(values) if values else 0.0


def _std(values: List[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return (sum((float(value) - avg) ** 2 for value in values) / len(values)) ** 0.5


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(100.0, percentile)) / 100.0 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


class MetricsEngine:
    """Computes and stores per-query metrics; aggregation is always a GROUP BY query."""

    def __init__(
        self,
        recall_at_k_values: List[int] = [1, 5, 10],
        precision_at_k_values: List[int] = [],
        ndcg_at_k_values: List[int] = [10],
        temporal_recall_at_k_values: List[int] = [],
        latency_percentile_values: List[int] = [50, 95, 99],
        compute_mrr: bool = True,
        compute_map: bool = True,
    ):
        self.recall_k = recall_at_k_values
        self.precision_k = precision_at_k_values
        self.ndcg_k = ndcg_at_k_values
        self.temporal_k = temporal_recall_at_k_values
        self.latency_percentiles = latency_percentile_values
        self.compute_mrr = compute_mrr
        self.compute_map = compute_map

    async def compute_and_store(
        self,
        run_id: str,
        store: BaseStore,
        results: List[Any],
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
                metric_rows: List[Dict[str, Any]] = []
                stage_snapshots = [snap] + list(snap.arms)
                for current in stage_snapshots:
                    branch_id = current.stage_id if current is not snap else None
                    doc_ids = dedupe_preserve_rank([d.id for d in current.documents])

                    # Recall@K (binary: grade > 0 = relevant)
                    for k in self.recall_k:
                        score = recall_at_k(doc_ids, relevant_set, k)
                        metric_rows.append(
                            self._metric_row(
                                run_id,
                                result.pipeline_id,
                                result.query_id,
                                current.stage_index,
                                "recall",
                                k,
                                score,
                                query_meta,
                                branch_id=branch_id,
                            )
                        )

                    # Precision@K
                    for k in self.precision_k:
                        score = precision_at_k(doc_ids, relevant_set, k)
                        metric_rows.append(
                            self._metric_row(
                                run_id,
                                result.pipeline_id,
                                result.query_id,
                                current.stage_index,
                                "precision",
                                k,
                                score,
                                query_meta,
                                branch_id=branch_id,
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
                                current.stage_index,
                                "ndcg",
                                k,
                                score,
                                query_meta,
                                branch_id=branch_id,
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
                                current.stage_index,
                                "mrr",
                                0,
                                score,
                                query_meta,
                                branch_id=branch_id,
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
                                current.stage_index,
                                "map",
                                0,
                                score,
                                query_meta,
                                branch_id=branch_id,
                            )
                        )

                    # Temporal Recall@K
                    if self.temporal_k and query and query.temporal_anchor:
                        for k in self.temporal_k:
                            score = temporal_recall_at_k(
                                current.documents, relevant_set, k, query.temporal_anchor
                            )
                            if corpus_documents:
                                score = temporal_recall_at_k_with_corpus(
                                    current.documents,
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
                                    current.stage_index,
                                    "temporal_recall",
                                    k,
                                    score,
                                    query_meta,
                                    branch_id=branch_id,
                                )
                            )

                    # Latency — store raw ms once; percentiles computed at aggregate time
                    metric_rows.append(
                        self._metric_row(
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            current.stage_index,
                            "latency_ms",
                            0,
                            current.latency_ms,
                            query_meta,
                            branch_id=branch_id,
                        )
                    )
                    for profile_name, profile_value in current.profiling.items():
                        metric_rows.append(
                            self._metric_row(
                                run_id,
                                result.pipeline_id,
                                result.query_id,
                                current.stage_index,
                                f"profile_{profile_name}",
                                0,
                                float(profile_value),
                                query_meta,
                                branch_id=branch_id,
                            )
                        )
                await self._save_metrics(store, metric_rows)

    def _find_final_span(self, trace) -> "OperatorSpan | None":
        """Return the final operator span: explicit final_op_id, or the span
        whose op_id is never referenced as a parent by another span."""
        fired = [s for s in trace.spans if s.status == "FIRED"]
        if not fired:
            return None
        if trace.final_op_id:
            for s in fired:
                if s.op_id == trace.final_op_id:
                    return s
        all_parent_ids: Set[str] = set()
        for s in fired:
            all_parent_ids.update(s.parent_ids)
        terminal = [s for s in fired if s.op_id not in all_parent_ids]
        return terminal[-1] if terminal else fired[-1]

    async def compute_from_traces(
        self,
        run_id: str,
        store: BaseStore,
        traces: list,
        qrels: Union[Dict[str, Set[str]], Dict[str, Dict[str, int]]],
        queries_by_id: Optional[Dict] = None,
    ) -> None:
        """Compute per-query metrics from RetrievalTraceV2 operator DAGs.

        Produces identical metric values to compute_and_store for linear
        pipelines — a linear recall funnel is just a special case of a DAG path.
        """
        _sample = next(iter(qrels.values()), None)
        _graded = isinstance(_sample, dict)

        for trace in traces:
            if trace.status != "OK":
                continue
            raw_qrel = qrels.get(trace.query_id)
            if not raw_qrel:
                continue
            query = queries_by_id.get(trace.query_id) if queries_by_id else None

            if _graded:
                relevant_set: Set[str] = {
                    doc_id for doc_id, grade in raw_qrel.items() if grade > 0
                }
                graded_qrel: Dict[str, int] = raw_qrel  # type: ignore[assignment]
            else:
                relevant_set = raw_qrel  # type: ignore[assignment]
                graded_qrel = {}

            if not relevant_set:
                continue

            query_meta = query.metadata if query else {}
            # Stage index must reflect position in the pipeline's fixed op order, not
            # position among FIRED-only spans: a gated stage (e.g. EXPAND) is SKIPPED_BY_GATE
            # for some queries and not others, so filtering to FIRED first would shift every
            # later stage's index per-query and silently corrupt cross-query metric averages
            # (different operators' scores would get averaged together under one stage_index).
            # A SKIPPED_BY_GATE span still gets a stage slot; its outputs are a passthrough of
            # its inputs by convention, so its recall/ndcg honestly equal the prior stage's.
            # ERROR/TIMEOUT spans carry no valid outputs and are excluded.
            fired_spans = [s for s in trace.spans if s.status in ("FIRED", "SKIPPED_BY_GATE")]

            # End-to-end latency for multi-operator traces
            if len(fired_spans) > 1:
                await self._save_metrics(
                    store,
                    [
                        {
                            "run_id": run_id,
                            "pipeline_id": trace.pipeline_id,
                            "query_id": trace.query_id,
                            "stage_index": -1,
                            "metric_name": "latency_ms",
                            "k": 0,
                            "value": trace.total_latency_ms,
                            "query_metadata_json": query_meta,
                        }
                    ],
                )

            # Bucket each span by its TOPOLOGICAL DEPTH (longest path from a root), not its
            # position in the span list, so parallel branches don't collapse into fake
            # sequential stages. When a depth layer holds a single node it is the "spine"
            # (branch_id=None); parallel nodes sharing a depth each get branch_id=op_id so
            # their per-node metrics stay distinct. A linear chain has one node per depth →
            # branch_id=None and stage_index==position, identical to compute_and_store.
            depth_by_op = self._span_depths(fired_spans)
            nodes_at_depth: Dict[int, int] = defaultdict(int)
            for op_id, depth in depth_by_op.items():
                nodes_at_depth[depth] += 1

            for span in fired_spans:
                stage_index = depth_by_op[span.op_id]
                branch_id = None if nodes_at_depth[stage_index] == 1 else span.op_id
                metric_rows: List[Dict[str, Any]] = []
                doc_ids = dedupe_preserve_rank([c.doc_id for c in span.outputs])

                for k in self.recall_k:
                    score = recall_at_k(doc_ids, relevant_set, k)
                    metric_rows.append(
                        self._metric_row(
                            run_id, trace.pipeline_id, trace.query_id,
                            stage_index, "recall", k, score, query_meta, branch_id=branch_id,
                        )
                    )

                for k in self.precision_k:
                    score = precision_at_k(doc_ids, relevant_set, k)
                    metric_rows.append(
                        self._metric_row(
                            run_id, trace.pipeline_id, trace.query_id,
                            stage_index, "precision", k, score, query_meta, branch_id=branch_id,
                        )
                    )

                for k in self.ndcg_k:
                    if _graded:
                        score = ndcg_at_k_graded(doc_ids, graded_qrel, k)
                    else:
                        score = ndcg_at_k(doc_ids, relevant_set, k)
                    metric_rows.append(
                        self._metric_row(
                            run_id, trace.pipeline_id, trace.query_id,
                            stage_index, "ndcg", k, score, query_meta, branch_id=branch_id,
                        )
                    )

                if self.compute_mrr:
                    score = mrr([doc_ids], [relevant_set])
                    metric_rows.append(
                        self._metric_row(
                            run_id, trace.pipeline_id, trace.query_id,
                            stage_index, "mrr", 0, score, query_meta, branch_id=branch_id,
                        )
                    )

                if self.compute_map:
                    from retrieval_observatory.metrics.ranking import average_precision
                    score = average_precision(doc_ids, relevant_set)
                    metric_rows.append(
                        self._metric_row(
                            run_id, trace.pipeline_id, trace.query_id,
                            stage_index, "map", 0, score, query_meta, branch_id=branch_id,
                        )
                    )

                metric_rows.append(
                    self._metric_row(
                        run_id, trace.pipeline_id, trace.query_id,
                        stage_index, "latency_ms", 0, span.latency_ms, query_meta, branch_id=branch_id,
                    )
                )
                await self._save_metrics(store, metric_rows)

    @staticmethod
    def _span_depths(fired_spans: list) -> Dict[str, int]:
        """Longest-path depth of every span from a root, counting only parents that also
        fired. Roots (no fired parent) are depth 0."""
        fired_ids = {s.op_id for s in fired_spans}
        span_by_id = {s.op_id: s for s in fired_spans}
        cache: Dict[str, int] = {}

        def depth_of(op_id: str, seen: frozenset) -> int:
            if op_id in cache:
                return cache[op_id]
            span = span_by_id[op_id]
            parents = [p for p in span.parent_ids if p in fired_ids and p not in seen]
            d = 0 if not parents else 1 + max(depth_of(p, seen | {op_id}) for p in parents)
            cache[op_id] = d
            return d

        return {s.op_id: depth_of(s.op_id, frozenset()) for s in fired_spans}

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
            group_key = (row["pipeline_id"], row["stage_index"], row["metric_name"], row["k"], row.get("branch_id"))
            groups[group_key].append(row["value"])

        aggregated: Dict[str, Any] = {}
        for (pipeline_id, stage_index, metric_name, k, branch_id), scores in groups.items():
            if metric_name == "latency_ms":
                # Expand into per-percentile entries; no bootstrap CI (not meaningful here)
                for p in self.latency_percentiles:
                    pct_value = _percentile(scores, p)
                    suffix = f"|branch={branch_id}" if branch_id else ""
                    pct_key = f"{pipeline_id}|stage{stage_index}|latency_p{p}@0{suffix}"
                    aggregated[pct_key] = {
                        "pipeline_id": pipeline_id,
                        "stage_index": stage_index,
                        "metric_name": f"latency_p{p}",
                        "k": 0,
                        "branch_id": branch_id,
                        "mean": pct_value,
                        "std": None,
                        "ci_low": None,
                        "ci_high": None,
                        "n": len(scores),
                        "zero_count": 0,
                        "zero_pct": 0.0,
                    }
                continue

            ci_low, ci_high = bootstrap_ci(scores, n_resamples=n_bootstrap)
            zero_count = sum(1 for score in scores if float(score) == 0.0)
            suffix = f"|branch={branch_id}" if branch_id else ""
            key = f"{pipeline_id}|stage{stage_index}|{metric_name}@{k}{suffix}"
            aggregated[key] = {
                "pipeline_id": pipeline_id,
                "stage_index": stage_index,
                "metric_name": metric_name,
                "k": k,
                "branch_id": branch_id,
                "mean": _mean(scores),
                "std": _std(scores),
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n": len(scores),
                "zero_count": zero_count,
                "zero_pct": round(zero_count / len(scores) * 100, 1),
            }

        # Stage-6 path: use trace-native run status counts when available.
        status_counts = await store.get_run_status_counts(run_id)
        if status_counts:
            timeout_count = int(status_counts.get("TIMEOUT", 0))
            error_count = int(status_counts.get("ERROR", 0))
            ok_count = int(status_counts.get("OK", 0))
            total = ok_count + timeout_count + error_count
            if total > 0:
                dropout_count = timeout_count + error_count
                for pipeline_id in sorted({value.get("pipeline_id") for value in aggregated.values() if value.get("pipeline_id")}):
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

        # Backward-compatible fallback when traces_v2 is unavailable.
        results = await store.get_results(run_id)
        by_pipeline: Dict[str, List[Any]] = defaultdict(list)
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
        branch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "query_id": query_id,
            "stage_index": stage_index,
            "metric_name": metric_name,
            "k": k,
            "value": value,
            "branch_id": branch_id,
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
                run_id=row["run_id"],
                pipeline_id=row["pipeline_id"],
                query_id=row["query_id"],
                stage_index=row["stage_index"],
                metric_name=row["metric_name"],
                k=row["k"],
                value=row["value"],
                branch_id=row.get("branch_id"),
                query_metadata=row["query_metadata_json"],
            )
