from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable

from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2
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

    async def save_trace_v2(self, trace: RetrievalTraceV2) -> None:
        ...

    async def get_trace_v2(self, trace_id: str) -> Optional[RetrievalTraceV2]:
        ...

    async def get_traces_v2(self, run_id: str) -> List[RetrievalTraceV2]:
        ...

    async def save_doc_edge(self, src_doc_id: str, dst_doc_id: str, edge_type: str, weight: float = 1.0) -> None:
        ...

    async def get_doc_neighbors(self, src_doc_id: str, edge_type: Optional[str] = None) -> List[Dict]:
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
        branch_id: Optional[str] = None,
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

    async def get_run_status_counts(self, run_id: str) -> Dict[str, int]:
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

    async def save_forge_queries(self, dataset_id: str, queries_json: str) -> None:
        ...

    async def get_forge_queries(
        self,
        dataset_id: str,
        scenario_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        query_type: Optional[str] = None,
        validated_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict]:
        ...

    # TraceLens — production retrieval observability

    async def save_trace(self, trace) -> None:
        ...

    async def save_traces_batch(self, traces) -> None:
        ...

    async def list_services(self) -> List[Dict]:
        ...

    async def list_traces(
        self,
        service: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        status: Optional[str] = None,
        difficulty: Optional[str] = None,
        suspected_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict]:
        ...

    async def get_trace(self, trace_id: str) -> Optional[Dict]:
        ...

    async def purge_traces(self, service: Optional[str] = None, older_than: Optional[str] = None) -> int:
        ...

    async def get_query_lineage(self, query_id: str) -> Dict:
        ...

    async def save_golden_set(self, name: str, queries_json: str) -> None:
        ...

    async def get_golden_set(self, name: str) -> Optional[str]:
        ...

    async def list_golden_sets(self) -> List[Dict]:
        ...

    async def save_reliability_snapshot(self, run_id: str, value: float, components: Dict) -> None:
        ...

    async def get_reliability_history(self, run_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        ...
