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
    def __init__(self, pipeline_id: str, retriever: Union[BaseRetriever, BaseReranker]):
        self.pipeline_id = pipeline_id
        self.retriever = retriever

    async def run(self, query: Query) -> PipelineResult:
        try:
            if asyncio.iscoroutinefunction(self.retriever.retrieve):
                result = await self.retriever.retrieve(query)
            else:
                result = await asyncio.to_thread(self.retriever.retrieve, query)

            snapshot = StageSnapshot(
                stage_index=0,
                stage_id=self.retriever.retriever_id,
                documents=result.documents,
                latency_ms=result.latency_ms,
            )
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=[snapshot],
                total_latency_ms=result.latency_ms,
                status="OK",
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
