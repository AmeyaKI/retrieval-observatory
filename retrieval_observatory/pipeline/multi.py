from __future__ import annotations

import asyncio
import traceback
from typing import List, Union

from retrieval_observatory.types import (
    BaseReranker,
    BaseRetriever,
    Document,
    PipelineResult,
    Query,
    StageSnapshot,
)


class MultiStagePipeline:
    """Chains retrievers and rerankers; each stage feeds its output into the next."""

    def __init__(
        self,
        pipeline_id: str,
        stages: List[Union[BaseRetriever, BaseReranker]],
        k_per_stage: List[int],
    ):
        if len(stages) != len(k_per_stage):
            raise ValueError("stages and k_per_stage must have equal length")
        self.pipeline_id = pipeline_id
        self.stages = stages
        self.k_per_stage = k_per_stage

    async def run(self, query: Query) -> PipelineResult:
        snapshots: List[StageSnapshot] = []
        total_latency = 0.0
        current_docs: List[Document] = []

        try:
            for i, (stage, k) in enumerate(zip(self.stages, self.k_per_stage)):
                stage_query = Query(
                    text=query.text,
                    k=k,
                    query_id=query.query_id,
                    temporal_anchor=query.temporal_anchor,
                    filters=query.filters,
                )

                if i == 0:
                    # First stage: retriever against the full corpus
                    if asyncio.iscoroutinefunction(stage.retrieve):
                        result = await stage.retrieve(stage_query)
                    else:
                        result = await asyncio.to_thread(stage.retrieve, stage_query)
                else:
                    # Subsequent stages: reranker receives prior docs as candidates
                    candidates = current_docs[:k]
                    if asyncio.iscoroutinefunction(stage.rerank):
                        result = await stage.rerank(stage_query, candidates)
                    else:
                        result = await asyncio.to_thread(stage.rerank, stage_query, candidates)

                current_docs = result.documents
                total_latency += result.latency_ms
                snapshots.append(
                    StageSnapshot(
                        stage_index=i,
                        stage_id=stage.retriever_id,
                        documents=result.documents,
                        latency_ms=result.latency_ms,
                    )
                )

            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=total_latency,
                status="OK",
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
