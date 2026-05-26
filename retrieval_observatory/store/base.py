from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable

from retrieval_observatory.types import PipelineResult


@runtime_checkable
class BaseStore(Protocol):
    async def init_db(self) -> None:
        ...

    async def save_run(self, run_id: str, experiment_name: str, config_json: str) -> None:
        ...

    async def finish_run(self, run_id: str) -> None:
        ...

    async def save_result(self, run_id: str, result: PipelineResult) -> None:
        ...

    async def save_metric(
        self,
        run_id: str,
        pipeline_id: str,
        query_id: str,
        stage_index: int,
        metric_name: str,
        k: int,
        value: float,
        query_metadata: Optional[Dict] = None,
    ) -> None:
        ...

    async def save_metrics_batch(
        self,
        rows: List[Dict],
    ) -> None:
        ...

    async def get_results(self, run_id: str) -> List[PipelineResult]:
        ...

    async def get_metrics(self, run_id: str) -> List[Dict]:
        ...

    async def cache_get(self, cache_key: str) -> str | None:
        ...

    async def cache_set(self, cache_key: str, result_json: str) -> None:
        ...

    async def list_runs(self) -> List[Dict]:
        ...
