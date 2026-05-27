from __future__ import annotations

import asyncio
import time
import traceback
from typing import Union

from retrieval_observatory.types import (
    BaseReranker,
    BaseRetriever,
    PipelineResult,
    Query,
    StageSnapshot,
)


class SingleStagePipeline:
    def __init__(self, pipeline_id: str, retriever: Union[BaseRetriever, BaseReranker], k: int = 10):
        self.pipeline_id = pipeline_id
        self.retriever = retriever
        self.k = k

    async def run(self, query: Query) -> PipelineResult:
        # Override query.k with the configured stage k so the retriever respects the config.
        # (BEIRDataset sets query.k=100 for all queries; without this, config k is silently ignored.)
        stage_query = Query(
            text=query.text,
            k=self.k,
            query_id=query.query_id,
            temporal_anchor=query.temporal_anchor,
            filters=query.filters,
            metadata=query.metadata,
        )
        try:
            if asyncio.iscoroutinefunction(self.retriever.retrieve):
                result = await self.retriever.retrieve(stage_query)
            else:
                result = await asyncio.to_thread(self.retriever.retrieve, stage_query)

            snapshot = StageSnapshot(
                stage_index=0,
                stage_id=self.retriever.retriever_id,
                documents=result.documents,
                latency_ms=result.latency_ms,
                profiling=result.profiling,
                candidate_count=len(result.documents),
            )
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=[snapshot],
                total_latency_ms=result.latency_ms,
                status="OK",
            )
        except asyncio.CancelledError:
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=[],
                total_latency_ms=0.0,
                status="TIMEOUT",
            )
        except Exception:
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=[],
                total_latency_ms=0.0,
                status="ERROR",
                error_traceback=traceback.format_exc(),
            )
