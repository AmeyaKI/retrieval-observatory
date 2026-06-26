from __future__ import annotations

import asyncio
import traceback
from typing import Any, Dict, List, Optional, Union

from retrieval_observatory.types import (
    BaseReranker,
    BaseRetriever,
    Document,
    PipelineResult,
    Query,
    RetrievalResult,
    StageSnapshot,
)


def _arms_from_result(result: RetrievalResult, stage_index: int) -> List[StageSnapshot]:
    arms: List[StageSnapshot] = []
    for arm in result.arm_results or []:
        arms.append(
            StageSnapshot(
                stage_index=stage_index,
                stage_id=arm.retriever_id,
                documents=arm.documents,
                latency_ms=arm.latency_ms,
                profiling=arm.profiling,
                candidate_count=len(arm.documents),
            )
        )
    return arms


class MultiStagePipeline:
    """Chains retrievers and rerankers; each stage feeds its output into the next."""

    def __init__(
        self,
        pipeline_id: str,
        stages: List[Union[BaseRetriever, BaseReranker]],
        k_per_stage: List[int],
        stage_configs: Optional[List[Optional[Dict[str, Any]]]] = None,
        stage_cache: Any = None,  # Optional[StageResultCache] — imported lazily to avoid circular
    ):
        if len(stages) != len(k_per_stage):
            raise ValueError("stages and k_per_stage must have equal length")
        self.pipeline_id = pipeline_id
        self.stages = stages
        self.k_per_stage = k_per_stage
        self.stage_configs = stage_configs or [None] * len(stages)
        self.stage_cache = stage_cache

    async def run(self, query: Query) -> PipelineResult:
        snapshots: List[StageSnapshot] = []
        total_latency = 0.0
        current_docs: List[Document] = []

        try:
            for i, (stage, k) in enumerate(zip(self.stages, self.k_per_stage)):
                # Check stage-level cache (shared across ablation combos with same stage config)
                cache_key = None
                if self.stage_cache is not None and self.stage_configs[i] is not None:
                    upstream_ids = [d.id for d in current_docs] if i > 0 else None
                    cache_key = self.stage_cache.key_for(
                        self.stage_configs[i], query.query_id, upstream_doc_ids=upstream_ids
                    )
                    cached_snap = await self.stage_cache.get(cache_key)
                    if cached_snap is not None:
                        snapshots.append(cached_snap)
                        current_docs = cached_snap.documents
                        total_latency += cached_snap.latency_ms
                        continue

                stage_query = Query(
                    text=query.text,
                    k=k,
                    query_id=query.query_id,
                    temporal_anchor=query.temporal_anchor,
                    filters=query.filters,
                    metadata=query.metadata,
                )

                if i == 0:
                    # First stage: retriever against the full corpus
                    if asyncio.iscoroutinefunction(stage.retrieve):
                        result = await stage.retrieve(stage_query)
                    else:
                        result = await asyncio.to_thread(stage.retrieve, stage_query)
                else:
                    # Subsequent stages: pass ALL prior-stage docs so the reranker can score
                    # every candidate — it truncates to query.k internally.
                    candidates = current_docs
                    if asyncio.iscoroutinefunction(stage.rerank):
                        result = await stage.rerank(stage_query, candidates)
                    else:
                        result = await asyncio.to_thread(stage.rerank, stage_query, candidates)

                current_docs = result.documents
                total_latency += result.latency_ms
                snapshot = StageSnapshot(
                    stage_index=i,
                    stage_id=stage.retriever_id,
                    documents=result.documents,
                    latency_ms=result.latency_ms,
                    profiling=result.profiling,
                    candidate_count=len(result.documents),
                    arms=_arms_from_result(result, stage_index=i),
                )
                snapshots.append(snapshot)

                if cache_key is not None and result.documents:
                    await self.stage_cache.set(cache_key, snapshot)

            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=total_latency,
                status="OK",
            )
        except asyncio.CancelledError:
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=total_latency,
                status="TIMEOUT",
            )
        except Exception:
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,  # preserve completed stages
                total_latency_ms=total_latency,
                status="ERROR",
                error_traceback=traceback.format_exc(),
            )
