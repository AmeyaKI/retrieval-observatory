from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import PurePath
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, runtime_checkable

from retrieval_observatory.tracing.model import RetrievalTrace


_BEIR_DATASETS = frozenset({
    "nfcorpus", "trec-covid", "nq", "hotpotqa", "fiqa", "arguana", "quora",
    "dbpedia-entity", "scidocs", "fever", "climate-fever", "scifact", "trec-news",
})


def normalize_dataset_name(name: str) -> str:
    """Normalize dataset identifiers for matching (e.g. beir/nfcorpus vs nfcorpus)."""
    name = (name or "").strip().lower()
    if name.startswith("beir/") or name not in _BEIR_DATASETS:
        return name
    return f"beir/{name}"


@runtime_checkable
class BaseStore(Protocol):
    async def save_analysis_record(self, kind: str, record_id: str, payload: Dict, version: int = 1) -> None: ...
    async def get_analysis_record(self, kind: str, record_id: str) -> Dict | None: ...
    async def list_analysis_records(self, kind: str) -> List[Dict]: ...
    async def save_cohort(self, cohort_id: str, payload: Dict, version: int) -> None: ...
    async def get_cohort(self, cohort_id: str) -> Dict | None: ...
    async def list_cohorts(self) -> List[Dict]: ...
    async def save_corpus_snapshot(self, snapshot_id: str, payload: Dict, version: int = 1) -> None: ...
    async def append_judgment(self, judgment_id: str, payload: Dict, version: int = 1) -> None: ...
    async def save_baseline(self, baseline_id: str, payload: Dict, version: int = 1) -> None: ...
    async def save_regression_check(self, check_id: str, payload: Dict, version: int = 1) -> None: ...
    async def append_alert(self, alert_id: str, payload: Dict, version: int = 1) -> None: ...
    async def init_db(self) -> None:
        ...

    async def save_run(self, run_id: str, experiment_name: str, config_json: str) -> None:
        ...

    async def finish_run(self, run_id: str) -> None:
        ...

    async def save_trace(self, trace: RetrievalTrace) -> None:
        ...

    async def save_traces(self, traces: Sequence[RetrievalTrace]) -> None:
        ...

    async def get_trace(self, trace_id: str) -> RetrievalTrace | None:
        ...

    async def list_traces(self, query: TraceQuery | None = None, *, service: str | None = None, limit: int | None = None) -> List[RetrievalTrace]:
        ...

    async def get_traces(self, run_id: str) -> List[RetrievalTrace]:
        ...

    async def list_services(self) -> List[ServiceSummary]:
        ...

    async def list_topology_variants(self, query: TraceQuery) -> List[TopologyVariant]:
        ...

    async def get_instrumentation_health(
        self,
        service_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> InstrumentationHealth | None:
        ...

    async def save_instrumentation_health(self, snapshot: InstrumentationHealth) -> None:
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

    async def save_diagnostics(self, run_id: str, query_id: str, findings) -> None:
        ...

    async def query_diagnostics(self, run_id: str, query_id: Optional[str] = None):
        ...

    async def save_run_queries(self, run_id: str, queries: List, dataset_name: str) -> None:
        ...

    async def get_run_queries(self, run_id: str) -> List[Dict]:
        ...

    async def save_qrels(self, run_id: str, qrels: Dict[str, Dict[str, int]]) -> None:
        ...

    async def get_qrels(self, run_id: str) -> Dict[str, Dict[str, int]]:
        ...

    async def list_runs_for_dataset(self, dataset_name: str) -> List[Dict]:
        ...

    async def get_labeled_query_rows(self, run_ids: List[str]) -> List[Dict]:
        ...

    async def save_forge_dataset(self, dataset_id: str, summary_json: str, corpus_path: str, output_dir: str) -> None:
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

    async def purge_traces(self, query: TraceQuery) -> int:
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

    async def replace_investigation_projection(
        self,
        scope: InvestigationScope,
        *,
        rows: Sequence[Mapping],
        summaries: Sequence[Mapping],
        derivation_version: str,
        judgment_digest: str,
        trace_count: int,
    ) -> None:
        ...

    async def get_investigation_projection(self, scope: InvestigationScope) -> Dict | None:
        ...

    async def list_investigation_projections(self, run_id: str) -> List[Dict]:
        ...

    async def list_investigation_pairs(
        self,
        scope: InvestigationScope,
        filters: InvestigationFilter | None = None,
        *,
        limit: int = 50,
        cursor: str | None = None,
        order: Literal["priority", "entity"] = "priority",
    ) -> InvestigationPage:
        ...

    async def get_investigation_pair(
        self, scope: InvestigationScope, *, trace_id: str, namespace: str, unit: str, entity_id: str
    ) -> Dict | None:
        ...

    async def list_investigation_summaries(
        self,
        scope: InvestigationScope,
        kind: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        key_prefix: str | None = None,
    ) -> InvestigationPage:
        ...

    async def get_investigation_summary(self, scope: InvestigationScope, kind: str, key: str) -> Dict | None:
        ...

    async def delete_investigation_projection(self, scope: InvestigationScope) -> None:
        ...


def json_default(value: Any) -> Any:
    """``json.dumps`` fallback for application objects inside trace payloads (candidate metadata
    such as ``datetime`` or ``Path``): persisted as text rather than failing the whole trace."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    return str(value)


@dataclass(frozen=True)
class TraceQuery:
    service_id: str | None = None
    run_id: str | None = None
    pipeline_id: str | None = None
    query_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    status: str | None = None
    topology_hash: str | None = None
    #: Page size. `None` means every matching trace.
    #:
    #: Defaulting this to a page size made truncation the silent behaviour and completeness
    #: the opt-in, which is backwards: a page is a presentation concern, while a statistic
    #: computed over "the run's traces" is a correctness one. Callers that genuinely page
    #: (the production trace browser, query evidence) pass a limit explicitly; callers that
    #: want a whole run were silently handed its first 200 queries.
    limit: int | None = None
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be positive")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")


@dataclass(frozen=True)
class ServiceSummary:
    service_id: str
    trace_count: int
    last_seen: datetime | None


@dataclass(frozen=True)
class TopologyVariant:
    topology_hash: str
    trace_count: int
    operator_ids: tuple[str, ...]


@dataclass(frozen=True)
class InstrumentationHealth:
    service_id: str
    accepted: int = 0
    exported: int = 0
    dropped: int = 0
    serialization_failures: int = 0
    retries: int = 0
    permanent_failures: int = 0
    queue_depth: int = 0
    queue_high_water: int = 0
    drop_reasons: Dict[str, int] = field(default_factory=dict)
    sample_rate: float = 1.0
    observed_at: datetime | None = None
    last_export_at: datetime | None = None
    last_flush_latency_ms: float | None = None


@dataclass(frozen=True)
class InvestigationScope:
    run_id: str
    pipeline_id: str
    evaluation_digest: str


@dataclass(frozen=True)
class InvestigationFilter:
    """Equality filters on `investigation_pairs` columns; `None` means no filter."""

    query_id: str | None = None
    trace_id: str | None = None
    namespace: str | None = None
    entity_id: str | None = None
    unit: str | None = None
    outcome: str | None = None
    judgment: str | None = None
    final_membership: str | None = None
    capture_state: str | None = None
    loss_boundary: str | None = None
    confusion: str | None = None


@dataclass(frozen=True)
class InvestigationPage:
    rows: List[Dict]
    total: int
    next_cursor: str | None


# Stable total orderings over one scope. `unit` closes the primary key
# (trace_id, namespace, unit, entity_id) so the keyset cursor can never skip or repeat a row.
INVESTIGATION_SORT_KEYS: Dict[str, tuple[str, ...]] = {
    "priority": ("priority", "query_id", "namespace", "entity_id", "trace_id", "unit"),
    "entity": ("namespace", "entity_id", "priority", "query_id", "trace_id", "unit"),
}
INVESTIGATION_PAGE_LIMIT = 200


def clamp_page_limit(limit: int) -> int:
    return max(1, min(int(limit), INVESTIGATION_PAGE_LIMIT))


def encode_cursor(values: Sequence[object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(values)).encode()).decode()


def decode_cursor(cursor: str, width: int) -> list:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("malformed pagination cursor") from exc
    if not isinstance(values, list) or len(values) != width:
        raise ValueError("malformed pagination cursor")
    return values


def investigation_where(
    scope: InvestigationScope,
    filters: InvestigationFilter | None,
    placeholder: Callable[[int], str],
    **extra: object,
) -> tuple[str, list]:
    """`WHERE` body and positional params for one scope plus equality filters.

    `placeholder(n)` renders the n-th (1-based) parameter for the backend's style.
    """
    pairs: list[tuple[str, object]] = [(f.name, getattr(scope, f.name)) for f in fields(scope)]
    if filters is not None:
        pairs.extend((f.name, getattr(filters, f.name)) for f in fields(filters))
    pairs.extend(extra.items())
    clauses: list[str] = []
    params: list = []
    for column, value in pairs:
        if value is not None:
            params.append(value)
            clauses.append(f"{column} = {placeholder(len(params))}")
    return " AND ".join(clauses), params


def like_prefix(prefix: str) -> str:
    """`LIKE` pattern matching keys that start with `prefix`; pair with `ESCAPE '\\'`."""
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def keyset_page(rows: Sequence[Sequence], limit: int, total: int) -> InvestigationPage:
    """Build a page from `limit + 1` rows shaped `(*sort_key, payload_json)`."""
    page = list(rows[:limit])
    next_cursor = encode_cursor(page[-1][:-1]) if len(rows) > limit else None
    return InvestigationPage(rows=[json.loads(row[-1]) for row in page], total=total, next_cursor=next_cursor)
