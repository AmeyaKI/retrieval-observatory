from __future__ import annotations

import asyncio
import traceback
from typing import Union

from typing import List, Optional

from retrieval_observatory.types import (
    BaseReranker,
    BaseRetriever,
    PipelineResult,
    Query,
    StageSnapshot,
)


def _as_pipeline_result(result, query_id: str, pipeline_id: str) -> Optional[PipelineResult]:
    """Coerce a multi-snapshot retriever return into a PipelineResult, else return None.

    Accepts a ready PipelineResult (re-stamped with this run's ids) or a list[StageSnapshot].
    """
    if isinstance(result, PipelineResult):
        result.query_id = query_id
        result.pipeline_id = pipeline_id
        return result
    if isinstance(result, list) and result and all(isinstance(s, StageSnapshot) for s in result):
        snapshots: List[StageSnapshot] = result
        return PipelineResult(
            query_id=query_id,
            pipeline_id=pipeline_id,
            snapshots=snapshots,
            total_latency_ms=sum(s.latency_ms for s in snapshots),
            status="OK",
        )
    return None


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

            # A wrapped monolithic retriever may report its own per-stage breakdown by returning a
            # PipelineResult or a list[StageSnapshot] instead of a single RetrievalResult. Pass it
            # through so per-stage diagnostics (candidate_miss vs reranker_drop) still fire.
            passthrough = _as_pipeline_result(result, query.query_id, self.pipeline_id)
            if passthrough is not None:
                return passthrough

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
