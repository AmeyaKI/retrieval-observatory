from __future__ import annotations

import asyncio
import os
import traceback
from typing import Dict, List, Optional, Set, Union

from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.runner.cache import ResultCache
from retrieval_observatory.runner.scheduler import interleave_tasks
from retrieval_observatory.store.base import BaseStore
from retrieval_observatory.tracing.lift import lift_pipeline_result
from retrieval_observatory.types import PipelineResult, Query

Pipeline = Union[SingleStagePipeline, MultiStagePipeline]

# HTTP status codes that warrant a retry (transient)
_TRANSIENT_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}


class BenchmarkRunner:
    def __init__(
        self,
        store: BaseStore,
        concurrency: int = 8,
        timeout_ms: int = 5000,
        retry_attempts: int = 2,
        caches: Optional[Dict[str, ResultCache]] = None,
    ):
        self.store = store
        self.concurrency = concurrency
        self.timeout_s = timeout_ms / 1000
        self.retry_attempts = retry_attempts
        self.caches = caches or {}

    async def run(
        self,
        pipelines: List[Pipeline],
        queries: List[Query],
        run_id: str,
    ) -> Dict[str, List[PipelineResult]]:
        """Execute all (pipeline, query) pairs and persist results atomically."""
        pipeline_map = {p.pipeline_id: p for p in pipelines}
        query_map = {q.query_id: q for q in queries}

        tasks = interleave_tasks(
            pipeline_ids=list(pipeline_map.keys()),
            query_ids=list(query_map.keys()),
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        results_by_pipeline: Dict[str, List[PipelineResult]] = {
            pid: [] for pid in pipeline_map
        }
        error_counts: Dict[str, int] = {pid: 0 for pid in pipeline_map}
        self.error_samples: List[str] = []  # first 3 unique error messages

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            TextColumn("[red]{task.fields[errors]} errors"),
        ) as progress:
            task_id = progress.add_task(
                "Benchmarking...",
                total=len(tasks),
                errors=0,
            )

            async def _run_one(pipeline_id: str, query_id: str) -> PipelineResult:
                pipeline = pipeline_map[pipeline_id]
                query = query_map[query_id]
                cache = self.caches.get(pipeline_id)

                dual_write = (
                    os.environ.get("RETOBS_DUAL_WRITE_TRACES", "1") != "0"
                    and hasattr(self.store, "save_trace_v2")
                )

                if cache:
                    cached = await cache.get(query_id)
                    if cached is not None:
                        if dual_write:
                            trace_v2 = lift_pipeline_result(cached, run_id=run_id)
                            await self.store.save_trace_v2(trace_v2)
                        return cached

                result = await self._run_with_retry(pipeline, query)

                await self.store.save_result(run_id, result)
                if dual_write:
                    trace_v2 = lift_pipeline_result(result, run_id=run_id)
                    await self.store.save_trace_v2(trace_v2)

                if cache and result.status == "OK":
                    await cache.set(query_id, result)

                return result

            async def _bounded(pipeline_id: str, query_id: str) -> PipelineResult:
                async with semaphore:
                    result = await _run_one(pipeline_id, query_id)
                    if result.status != "OK":
                        error_counts[pipeline_id] += 1
                        if result.error_traceback and len(self.error_samples) < 3:
                            # Collect unique error types for post-run display
                            first_line = result.error_traceback.strip().splitlines()[-1]
                            if first_line not in self.error_samples:
                                self.error_samples.append(first_line)
                    results_by_pipeline[pipeline_id].append(result)
                    total_errors = sum(error_counts.values())
                    progress.update(task_id, advance=1, errors=total_errors)
                    return result

            await asyncio.gather(*[_bounded(pid, qid) for pid, qid in tasks])

        return results_by_pipeline

    async def _run_with_retry(self, pipeline: Pipeline, query: Query) -> PipelineResult:
        last_result: Optional[PipelineResult] = None
        for attempt in range(self.retry_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    pipeline.run(query), timeout=self.timeout_s
                )
                if result.status == "OK":
                    return result
                # Don't retry ERROR — only transient failures should retry
                last_result = result
                if result.status == "ERROR":
                    return result
            except asyncio.TimeoutError:
                last_result = PipelineResult(
                    query_id=query.query_id,
                    pipeline_id=pipeline.pipeline_id,
                    snapshots=[],
                    total_latency_ms=self.timeout_s * 1000,
                    status="TIMEOUT",
                )
                # Timeouts are not retried — they indicate a slow endpoint
                return last_result
            except Exception:
                last_result = PipelineResult(
                    query_id=query.query_id,
                    pipeline_id=pipeline.pipeline_id,
                    snapshots=[],
                    total_latency_ms=0.0,
                    status="ERROR",
                    error_traceback=traceback.format_exc(),
                )
                if attempt < self.retry_attempts:
                    await asyncio.sleep(2 ** attempt * 0.5)  # exponential backoff

        return last_result  # type: ignore[return-value]
