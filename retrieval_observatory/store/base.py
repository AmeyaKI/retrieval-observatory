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

    async def save_run_manifest(self, run_id: str, manifest: Dict) -> None:
        ...

    async def get_run_manifest(self, run_id: str) -> Optional[Dict]:
        ...

    async def save_validation_report(
        self,
        report: Dict,
        config_path: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        ...

    async def save_query_diagnostics(self, rows: List[Dict]) -> None:
        ...

    async def get_query_diagnostics(self, run_id: str, query_id: Optional[str] = None) -> List[Dict]:
        ...

    async def save_run_queries(self, run_id: str, queries: List, dataset_name: str) -> None:
        ...

    async def get_run_queries(self, run_id: str) -> List[Dict]:
        ...

    async def list_runs_for_dataset(self, dataset_name: str) -> List[Dict]:
        ...

    async def get_labeled_query_rows(self, run_ids: List[str]) -> List[Dict]:
        ...

    async def save_forge_dataset(self, dataset_id: str, summary_json: str, corpus_path: str, output_dir: str) -> None:
        ...

    async def get_forge_datasets(self) -> List[Dict]:
        ...

    async def save_forge_scenarios(self, dataset_id: str, scenarios_json: str) -> None:
        ...

    async def get_forge_scenarios(self, dataset_id: str) -> List[Dict]:
        ...
