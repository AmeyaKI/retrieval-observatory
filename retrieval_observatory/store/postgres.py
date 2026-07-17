from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from retrieval_observatory.store.base import (
    InstrumentationHealth,
    ServiceSummary,
    TopologyVariant,
    TraceQuery,
)
from retrieval_observatory.tracing.model import RetrievalTrace

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    experiment_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    config_json TEXT NOT NULL
)
"""


_CREATE_METRIC_SCORES = """
CREATE TABLE IF NOT EXISTS metric_scores (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    pipeline_id TEXT,
    query_id TEXT,
    stage_index INT,
    metric_name TEXT,
    k INT,
    value REAL,
    branch_id TEXT,
    query_metadata_json TEXT DEFAULT NULL
)
"""
_MIGRATE_METRIC_SCORES_BRANCH_ID = "ALTER TABLE metric_scores ADD COLUMN branch_id TEXT"
_MIGRATE_QUERY_DIAGNOSTIC_EVIDENCE = (
    "ALTER TABLE query_diagnostics ADD COLUMN diagnostic_evidence_json TEXT NOT NULL DEFAULT '[]'"
)
_MIGRATE_FORGE_QUERY_METADATA = (
    "ALTER TABLE forge_queries ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
)

_CREATE_CACHE = """
CREATE TABLE IF NOT EXISTS result_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
)
"""

_CREATE_ANALYSIS_RECORDS = """
CREATE TABLE IF NOT EXISTS analysis_records (
    kind TEXT NOT NULL, record_id TEXT NOT NULL, version INT NOT NULL,
    payload_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (kind, record_id, version)
)
"""

_CREATE_RUN_MANIFESTS = """
CREATE TABLE IF NOT EXISTS run_manifests (
    run_id TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
)
"""

_CREATE_RUN_QRELS = """
CREATE TABLE IF NOT EXISTS run_qrels (
    run_id TEXT PRIMARY KEY,
    qrels_json TEXT NOT NULL
)
"""

_CREATE_VALIDATION_REPORTS = """
CREATE TABLE IF NOT EXISTS validation_reports (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    config_path TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    report_json TEXT NOT NULL
)
"""

_CREATE_QUERY_DIAGNOSTICS = """
CREATE TABLE IF NOT EXISTS query_diagnostics (
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    difficulty_bucket TEXT NOT NULL,
    failure_labels_json TEXT NOT NULL,
    missing_relevant_ids_json TEXT NOT NULL,
    stage_hits_json TEXT NOT NULL,
    diagnostic_evidence_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, query_id, pipeline_id)
)
"""

_CREATE_DIAGNOSTIC_FINDINGS = """
CREATE TABLE IF NOT EXISTS diagnostic_findings (
    run_id TEXT NOT NULL, query_id TEXT NOT NULL, trace_id TEXT NOT NULL,
    label TEXT NOT NULL, availability TEXT NOT NULL, method_id TEXT,
    method_version TEXT, evidence_class TEXT, finding_order INTEGER NOT NULL, finding_json JSONB NOT NULL,
    PRIMARY KEY (run_id, query_id, trace_id, label)
)
"""

_CREATE_RUN_QUERIES = """
CREATE TABLE IF NOT EXISTS run_queries (
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    PRIMARY KEY (run_id, query_id)
)
"""

_CREATE_FORGE_DATASETS = """
CREATE TABLE IF NOT EXISTS forge_datasets (
    dataset_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    corpus_path TEXT NOT NULL DEFAULT '',
    output_dir TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL
)
"""

_CREATE_FORGE_SCENARIOS = """
CREATE TABLE IF NOT EXISTS forge_scenarios (
    id SERIAL PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    scenario_type TEXT NOT NULL,
    anchor_doc_ids_json TEXT NOT NULL,
    evidence_summary TEXT NOT NULL
)
"""

_CREATE_FORGE_QUERIES = """
CREATE TABLE IF NOT EXISTS forge_queries (
    id SERIAL PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    text TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    difficulty_label TEXT NOT NULL,
    failure_category TEXT,
    validated INT NOT NULL DEFAULT 0,
    positive_doc_ids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}'
)
"""

_CREATE_TRACES = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    run_id TEXT,
    query_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    topology_hash TEXT NOT NULL,
    trace_json JSONB NOT NULL
)
"""
_CREATE_TRACES_SERVICE_IDX = "CREATE INDEX IF NOT EXISTS idx_traces_service_time ON traces(service_id, timestamp DESC)"
_CREATE_TRACES_RUN_IDX = "CREATE INDEX IF NOT EXISTS idx_traces_run_query ON traces(run_id, query_id)"
_CREATE_TRACES_TOPOLOGY_IDX = "CREATE INDEX IF NOT EXISTS idx_traces_pipeline_topology ON traces(pipeline_id, topology_hash)"

_CREATE_INSTRUMENTATION_HEALTH = """
CREATE TABLE IF NOT EXISTS instrumentation_health (
    id BIGSERIAL PRIMARY KEY,
    service_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    health_json JSONB NOT NULL
)
"""

_CREATE_GOLDEN_SETS = """
CREATE TABLE IF NOT EXISTS golden_sets (
    name TEXT PRIMARY KEY,
    queries_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_RELIABILITY_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS reliability_snapshots (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    components_json TEXT NOT NULL
)
"""


_CREATE_DOC_EDGES = """
CREATE TABLE IF NOT EXISTS doc_edges (
    id SERIAL PRIMARY KEY,
    src_doc_id TEXT NOT NULL,
    dst_doc_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0
)
"""
_CREATE_DOC_EDGES_SRC_IDX = "CREATE INDEX IF NOT EXISTS idx_doc_edges_src ON doc_edges(src_doc_id, edge_type)"
_CREATE_DOC_EDGES_DST_IDX = "CREATE INDEX IF NOT EXISTS idx_doc_edges_dst ON doc_edges(dst_doc_id, edge_type)"


class PostgresStore:
    """Async Postgres backend using asyncpg connection pooling."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self.dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            try:
                import asyncpg
            except ImportError as e:
                raise ImportError(
                    "Postgres support requires asyncpg. "
                    "Install with: pip install retrieval-observatory[postgres]"
                ) from e
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )
        return self._pool

    async def init_db(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_RUNS)
            await conn.execute(_CREATE_METRIC_SCORES)
            await conn.execute(_CREATE_CACHE)
            await conn.execute(_CREATE_ANALYSIS_RECORDS)
            await conn.execute(_CREATE_RUN_MANIFESTS)
            await conn.execute(_CREATE_RUN_QRELS)
            await conn.execute(_CREATE_VALIDATION_REPORTS)
            await conn.execute(_CREATE_QUERY_DIAGNOSTICS)
            await conn.execute(_CREATE_DIAGNOSTIC_FINDINGS)
            await conn.execute(_CREATE_RUN_QUERIES)
            await conn.execute(_CREATE_FORGE_DATASETS)
            await conn.execute(_CREATE_FORGE_SCENARIOS)
            await conn.execute(_CREATE_FORGE_QUERIES)
            await conn.execute(_CREATE_TRACES)
            await conn.execute(_CREATE_TRACES_SERVICE_IDX)
            await conn.execute(_CREATE_TRACES_RUN_IDX)
            await conn.execute(_CREATE_TRACES_TOPOLOGY_IDX)
            await conn.execute(_CREATE_INSTRUMENTATION_HEALTH)
            await conn.execute(_CREATE_GOLDEN_SETS)
            await conn.execute(_CREATE_RELIABILITY_SNAPSHOTS)
            await conn.execute(_CREATE_DOC_EDGES)
            await conn.execute(_CREATE_DOC_EDGES_SRC_IDX)
            await conn.execute(_CREATE_DOC_EDGES_DST_IDX)
            try:
                await conn.execute(_MIGRATE_METRIC_SCORES_BRANCH_ID)
            except Exception:
                pass
            try:
                await conn.execute(_MIGRATE_QUERY_DIAGNOSTIC_EVIDENCE)
            except Exception:
                pass
            try:
                await conn.execute(_MIGRATE_FORGE_QUERY_METADATA)
            except Exception:
                pass

    async def save_run(self, run_id: str, experiment_name: str, config_json: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO runs (run_id, experiment_name, started_at, config_json)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (run_id) DO UPDATE
                   SET experiment_name = EXCLUDED.experiment_name,
                       config_json = EXCLUDED.config_json""",
                run_id,
                experiment_name,
                datetime.now(timezone.utc),
                config_json,
            )

    async def finish_run(self, run_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE runs SET finished_at = $1 WHERE run_id = $2",
                datetime.now(timezone.utc),
                run_id,
            )

    async def save_doc_edge(
        self,
        src_doc_id: str,
        dst_doc_id: str,
        edge_type: str,
        weight: float = 1.0,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO doc_edges (src_doc_id, dst_doc_id, edge_type, weight) VALUES ($1, $2, $3, $4)",
                src_doc_id,
                dst_doc_id,
                edge_type,
                weight,
            )

    async def get_doc_neighbors(self, src_doc_id: str, edge_type: Optional[str] = None) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if edge_type:
                rows = await conn.fetch(
                    "SELECT src_doc_id, dst_doc_id, edge_type, weight FROM doc_edges WHERE src_doc_id = $1 AND edge_type = $2",
                    src_doc_id,
                    edge_type,
                )
            else:
                rows = await conn.fetch(
                    "SELECT src_doc_id, dst_doc_id, edge_type, weight FROM doc_edges WHERE src_doc_id = $1",
                    src_doc_id,
                )
        return [dict(row) for row in rows]

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
        # save_metrics_batch does its own json.dumps on query_metadata_json, so pass
        # the raw dict through here -- pre-serializing it double-encodes the JSON.
        await self.save_metrics_batch(
            rows=[
                {
                    "run_id": run_id,
                    "pipeline_id": pipeline_id,
                    "query_id": query_id,
                    "stage_index": stage_index,
                    "metric_name": metric_name,
                    "k": k,
                    "value": value,
                    "branch_id": branch_id,
                    "query_metadata_json": query_metadata,
                }
            ]
        )

    async def save_metrics_batch(self, rows: List[Dict]) -> None:
        if not rows:
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO metric_scores
                   (run_id, pipeline_id, query_id, stage_index, metric_name, k, value, branch_id, query_metadata_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                [
                    (
                        row["run_id"],
                        row["pipeline_id"],
                        row["query_id"],
                        row["stage_index"],
                        row["metric_name"],
                        row["k"],
                        row["value"],
                        row.get("branch_id"),
                        json.dumps(row["query_metadata_json"]) if row.get("query_metadata_json") else None,
                    )
                    for row in rows
                ],
            )

    async def get_metrics(self, run_id: str) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM metric_scores WHERE run_id = $1", run_id
            )
        result = []
        for row in rows:
            d = dict(row)
            if d.get("query_metadata_json"):
                d["query_metadata"] = json.loads(d["query_metadata_json"])
            else:
                d["query_metadata"] = {}
            result.append(d)
        return result

    async def get_run_status_counts(self, run_id: str) -> Dict[str, int]:
        pool = await self._get_pool()
        counts: Dict[str, int] = {}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM traces WHERE run_id = $1 GROUP BY status",
                run_id,
            )
        for row in rows:
            counts[str(row["status"])] = int(row["n"])
        return counts

    async def cache_get(self, cache_key: str) -> Optional[str]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT result_json FROM result_cache WHERE cache_key = $1", cache_key
            )
        return row["result_json"] if row else None

    async def cache_set(self, cache_key: str, result_json: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO result_cache (cache_key, result_json) VALUES ($1, $2)
                   ON CONFLICT (cache_key) DO UPDATE SET result_json = EXCLUDED.result_json""",
                cache_key,
                result_json,
            )

    async def list_runs(self) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM runs ORDER BY started_at DESC")
        return [dict(row) for row in rows]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def save_run_manifest(self, run_id: str, manifest: Dict) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO run_manifests (run_id, manifest_json) VALUES ($1, $2)
                   ON CONFLICT (run_id) DO UPDATE SET manifest_json = EXCLUDED.manifest_json""",
                run_id,
                json.dumps(manifest, sort_keys=True),
            )

    async def get_run_manifest(self, run_id: str) -> Optional[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT manifest_json FROM run_manifests WHERE run_id = $1", run_id)
        return json.loads(row["manifest_json"]) if row else None

    async def save_qrels(self, run_id: str, qrels: Dict[str, Dict[str, int]]) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO run_qrels (run_id, qrels_json) VALUES ($1, $2)
                   ON CONFLICT (run_id) DO UPDATE SET qrels_json = EXCLUDED.qrels_json""",
                run_id,
                json.dumps(qrels),
            )

    async def get_qrels(self, run_id: str) -> Dict[str, Dict[str, int]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT qrels_json FROM run_qrels WHERE run_id = $1", run_id)
        return json.loads(row["qrels_json"]) if row else {}

    async def save_validation_report(
        self,
        report: Dict,
        config_path: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO validation_reports (run_id, config_path, created_at, report_json)
                   VALUES ($1, $2, $3, $4)""",
                run_id,
                config_path,
                datetime.now(timezone.utc),
                json.dumps(report),
            )

    async def save_query_diagnostics(self, rows: List[Dict]) -> None:
        if not rows:
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO query_diagnostics
                   (run_id, query_id, pipeline_id, difficulty_bucket, failure_labels_json,
                    missing_relevant_ids_json, stage_hits_json, diagnostic_evidence_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (run_id, query_id, pipeline_id) DO UPDATE SET
                       difficulty_bucket = EXCLUDED.difficulty_bucket,
                       failure_labels_json = EXCLUDED.failure_labels_json,
                       missing_relevant_ids_json = EXCLUDED.missing_relevant_ids_json,
                       stage_hits_json = EXCLUDED.stage_hits_json,
                       diagnostic_evidence_json = EXCLUDED.diagnostic_evidence_json""",
                [
                    (
                        row["run_id"],
                        row["query_id"],
                        row["pipeline_id"],
                        row["difficulty_bucket"],
                        json.dumps(row.get("failure_labels", [])),
                        json.dumps(row.get("missing_relevant_ids", [])),
                        json.dumps(row.get("stage_hits", {})),
                        json.dumps(row.get("diagnostic_evidence", [])),
                    )
                    for row in rows
                ],
            )

    async def get_query_diagnostics(self, run_id: str, query_id: Optional[str] = None) -> List[Dict]:
        pool = await self._get_pool()
        sql = "SELECT * FROM query_diagnostics WHERE run_id = $1"
        params = [run_id]
        if query_id is not None:
            sql += " AND query_id = $2"
            params.append(query_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        result = []
        for row in rows:
            item = dict(row)
            item["failure_labels"] = json.loads(item.pop("failure_labels_json"))
            item["missing_relevant_ids"] = json.loads(item.pop("missing_relevant_ids_json"))
            item["stage_hits"] = json.loads(item.pop("stage_hits_json"))
            item["diagnostic_evidence"] = json.loads(item.pop("diagnostic_evidence_json", "[]"))
            result.append(item)
        return result

    async def save_diagnostics(self, run_id: str, query_id: str, findings) -> None:
        if not findings:
            return
        trace_id = next((f.evidence.trace_ids[0] for f in findings if f.evidence and f.evidence.trace_ids), "")
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO diagnostic_findings
                   (run_id, query_id, trace_id, label, availability, method_id, method_version, evidence_class, finding_order, finding_json)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
                   ON CONFLICT (run_id, query_id, trace_id, label) DO UPDATE SET
                   availability=EXCLUDED.availability, method_id=EXCLUDED.method_id,
                   method_version=EXCLUDED.method_version, evidence_class=EXCLUDED.evidence_class,
                   finding_order=EXCLUDED.finding_order,
                   finding_json=EXCLUDED.finding_json""",
                [(run_id, query_id, trace_id, f.label,
                  f.availability.value, f.evidence.method_id if f.evidence else None,
                  f.evidence.method_version if f.evidence else None, f.evidence.evidence_class if f.evidence else None,
                  index, json.dumps(f.to_dict())) for index, f in enumerate(findings)],
            )
        await self.save_query_diagnostics([{
            "run_id": run_id,
            "query_id": query_id,
            "pipeline_id": "typed_findings",
            "difficulty_bucket": "unknown",
            "failure_labels": [f.label for f in findings if f.availability.value == "supported"],
            "missing_relevant_ids": [],
            "stage_hits": {},
            "diagnostic_evidence": [f.to_dict() for f in findings],
        }])

    async def query_diagnostics(self, run_id: str, query_id: Optional[str] = None):
        from retrieval_observatory.diagnostics.model import DiagnosticFinding
        pool = await self._get_pool()
        sql, params = "SELECT finding_json FROM diagnostic_findings WHERE run_id = $1", [run_id]
        if query_id is not None:
            sql += " AND query_id = $2"
            params.append(query_id)
        sql += " ORDER BY query_id, trace_id, finding_order"
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [DiagnosticFinding.from_dict(dict(row["finding_json"])) for row in rows]

    async def save_run_queries(
        self,
        run_id: str,
        queries: List,
        dataset_name: str,
    ) -> None:
        if not queries:
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO run_queries (run_id, query_id, query_text, dataset_name)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (run_id, query_id) DO UPDATE SET
                       query_text = EXCLUDED.query_text,
                       dataset_name = EXCLUDED.dataset_name""",
                [
                    (run_id, q.query_id, q.text, dataset_name)
                    for q in queries
                ],
            )

    async def get_run_queries(self, run_id: str) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM run_queries WHERE run_id = $1", run_id
            )
        return [dict(row) for row in rows]

    async def list_runs_for_dataset(self, dataset_name: str) -> List[Dict]:
        from retrieval_observatory.classifier.labels import normalize_dataset_name

        target = normalize_dataset_name(dataset_name)
        runs = await self.list_runs()
        matched = []
        for run in runs:
            try:
                config = json.loads(run["config_json"])
                name = normalize_dataset_name(config.get("dataset", {}).get("name", ""))
                if name == target:
                    matched.append(run)
            except (json.JSONDecodeError, TypeError):
                continue
        return matched

    async def get_labeled_query_rows(self, run_ids: List[str]) -> List[Dict]:
        if not run_ids:
            return []
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT run_id, query_id, difficulty_bucket
                   FROM query_diagnostics
                   WHERE run_id = ANY($1::text[])
                     AND difficulty_bucket != 'unknown'
                   GROUP BY run_id, query_id, difficulty_bucket""",
                run_ids,
            )
        return [dict(row) for row in rows]

    async def save_forge_dataset(
        self,
        dataset_id: str,
        summary_json: str,
        corpus_path: str,
        output_dir: str,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO forge_datasets (dataset_id, created_at, corpus_path, output_dir, summary_json)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (dataset_id) DO UPDATE SET
                       created_at = EXCLUDED.created_at,
                       corpus_path = EXCLUDED.corpus_path,
                       output_dir = EXCLUDED.output_dir,
                       summary_json = EXCLUDED.summary_json""",
                dataset_id,
                datetime.now(timezone.utc),
                corpus_path,
                output_dir,
                summary_json,
            )

    async def get_forge_datasets(self) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT dataset_id, created_at, corpus_path, output_dir, summary_json FROM forge_datasets ORDER BY created_at DESC"
            )
        result = []
        for row in rows:
            d = dict(row)
            try:
                from retrieval_observatory.forge.types import TestSetSummary

                d["summary"] = TestSetSummary.from_dict(
                    json.loads(d.pop("summary_json", "{}")),
                    dataset_id=d["dataset_id"],
                ).to_dict()
            except Exception:
                d["summary"] = TestSetSummary.from_dict({}, dataset_id=d["dataset_id"]).to_dict()
            result.append(d)
        return result

    async def save_forge_scenarios(self, dataset_id: str, scenarios_json: str) -> None:
        scenarios = json.loads(scenarios_json)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM forge_scenarios WHERE dataset_id = $1", dataset_id)
            for s in scenarios:
                await conn.execute(
                    """INSERT INTO forge_scenarios
                       (dataset_id, scenario_id, scenario_type, anchor_doc_ids_json, evidence_summary)
                       VALUES ($1, $2, $3, $4, $5)""",
                    dataset_id,
                    s.get("scenario_id", ""),
                    s.get("scenario_type", ""),
                    json.dumps(s.get("anchor_doc_ids", [])),
                    s.get("evidence_summary", ""),
                )

    async def get_forge_scenarios(self, dataset_id: str) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT scenario_id, scenario_type, anchor_doc_ids_json, evidence_summary
                   FROM forge_scenarios WHERE dataset_id = $1""",
                dataset_id,
            )
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["anchor_doc_ids"] = json.loads(d.pop("anchor_doc_ids_json", "[]"))
            except Exception:
                d["anchor_doc_ids"] = []
            result.append(d)
        return result

    async def save_forge_queries(self, dataset_id: str, queries_json: str) -> None:
        queries = json.loads(queries_json)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM forge_queries WHERE dataset_id = $1", dataset_id)
            for q in queries:
                await conn.execute(
                    """INSERT INTO forge_queries
                       (dataset_id, query_id, text, scenario_id, query_type, difficulty_label,
                        failure_category, validated, positive_doc_ids_json, metadata_json)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    dataset_id,
                    q.get("query_id", ""),
                    q.get("text", ""),
                    q.get("scenario_id", ""),
                    q.get("query_type", ""),
                    q.get("difficulty_label", "medium"),
                    q.get("failure_category"),
                    1 if q.get("validated") else 0,
                    json.dumps(q.get("positive_doc_ids", [])),
                    json.dumps(q.get("metadata", {})),
                )

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
        where = ["q.dataset_id = $1"]
        params: List = [dataset_id]
        idx = 2
        if difficulty:
            where.append(f"q.difficulty_label = ${idx}")
            params.append(difficulty)
            idx += 1
        if query_type:
            where.append(f"q.query_type = ${idx}")
            params.append(query_type)
            idx += 1
        if validated_only:
            where.append("q.validated = 1")
        join = ""
        if scenario_type:
            join = "JOIN forge_scenarios s ON s.dataset_id = q.dataset_id AND s.scenario_id = q.scenario_id"
            where.append(f"s.scenario_type = ${idx}")
            params.append(scenario_type)
            idx += 1
        sql = (
            "SELECT q.query_id, q.text, q.scenario_id, q.query_type, q.difficulty_label, "
            "q.failure_category, q.validated, q.positive_doc_ids_json, q.metadata_json "
            f"FROM forge_queries q {join} WHERE " + " AND ".join(where) +
            f" ORDER BY q.id LIMIT ${idx} OFFSET ${idx + 1}"
        )
        params.extend([limit, offset])
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        result = []
        for row in rows:
            d = dict(row)
            d["validated"] = bool(d.get("validated"))
            try:
                d["positive_doc_ids"] = json.loads(d.pop("positive_doc_ids_json", "[]"))
            except Exception:
                d["positive_doc_ids"] = []
            try:
                d["provenance"] = json.loads(d.pop("metadata_json", "{}"))
            except Exception:
                d["provenance"] = {}
            result.append(d)
        return result

    async def save_trace(self, trace: RetrievalTrace) -> None:
        await self.save_traces([trace])

    async def save_traces(self, traces: List[RetrievalTrace]) -> None:
        if not traces:
            return
        rows = [
            (
                trace.trace_id,
                trace.service_id,
                trace.run_id,
                trace.query_id,
                trace.pipeline_id,
                trace.status,
                trace.timestamp,
                trace.topology_hash(),
                json.dumps(trace.to_dict(), sort_keys=True),
            )
            for trace in traces
        ]
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    """INSERT INTO traces
                       (trace_id, service_id, run_id, query_id, pipeline_id, status,
                        timestamp, topology_hash, trace_json)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                       ON CONFLICT (trace_id) DO UPDATE SET
                           service_id = EXCLUDED.service_id,
                           run_id = EXCLUDED.run_id,
                           query_id = EXCLUDED.query_id,
                           pipeline_id = EXCLUDED.pipeline_id,
                           status = EXCLUDED.status,
                           timestamp = EXCLUDED.timestamp,
                           topology_hash = EXCLUDED.topology_hash,
                           trace_json = EXCLUDED.trace_json""",
                    rows,
                )

    async def list_services(self) -> List[ServiceSummary]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT service_id, COUNT(*) AS trace_count, MAX(timestamp) AS last_seen
                   FROM traces GROUP BY service_id ORDER BY last_seen DESC"""
            )
        return [ServiceSummary(r["service_id"], int(r["trace_count"]), r["last_seen"]) for r in rows]

    async def list_traces(self, query: TraceQuery | None = None, *, service: str | None = None, limit: int | None = None) -> List[RetrievalTrace]:
        if query is None:
            query = TraceQuery(service_id=service, limit=limit or 200)
        clauses: List[str] = []
        params: List = []
        for column, value in (
            ("service_id", query.service_id),
            ("run_id", query.run_id),
            ("pipeline_id", query.pipeline_id),
            ("query_id", query.query_id),
            ("status", query.status),
            ("topology_hash", query.topology_hash),
        ):
            if value is not None:
                params.append(value)
                clauses.append(f"{column} = ${len(params)}")
        if query.since is not None:
            params.append(query.since)
            clauses.append(f"timestamp >= ${len(params)}")
        if query.until is not None:
            params.append(query.until)
            clauses.append(f"timestamp <= ${len(params)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((query.limit, query.offset))
        sql = (
            f"SELECT trace_json FROM traces{where} ORDER BY timestamp DESC, trace_id "
            f"LIMIT ${len(params) - 1} OFFSET ${len(params)}"
        )
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [RetrievalTrace.from_dict(dict(row["trace_json"])) for row in rows]

    async def get_traces(self, run_id: str) -> List[RetrievalTrace]:
        return await self.list_traces(TraceQuery(run_id=run_id))

    async def get_trace(self, trace_id: str) -> Optional[RetrievalTrace]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT trace_json FROM traces WHERE trace_id = $1", trace_id)
        return RetrievalTrace.from_dict(dict(row["trace_json"])) if row else None

    async def list_topology_variants(self, query: TraceQuery) -> List[TopologyVariant]:
        traces = await self.list_traces(query)
        grouped: Dict[str, List[RetrievalTrace]] = {}
        for trace in traces:
            grouped.setdefault(trace.topology_hash(), []).append(trace)
        return [
            TopologyVariant(key, len(items), tuple(sorted({s.op_id for t in items for s in t.spans})))
            for key, items in sorted(grouped.items())
        ]

    async def save_instrumentation_health(self, snapshot: InstrumentationHealth) -> None:
        observed_at = snapshot.observed_at or datetime.now(timezone.utc)
        payload = {**snapshot.__dict__, "observed_at": observed_at.isoformat()}
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO instrumentation_health (service_id, observed_at, health_json) VALUES ($1, $2, $3::jsonb)",
                snapshot.service_id, observed_at, json.dumps(payload, sort_keys=True),
            )

    async def get_instrumentation_health(self, service_id: str) -> Optional[InstrumentationHealth]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT health_json FROM instrumentation_health WHERE service_id = $1 ORDER BY observed_at DESC LIMIT 1",
                service_id,
            )
        if not row:
            return None
        payload = dict(row["health_json"])
        payload["observed_at"] = datetime.fromisoformat(payload["observed_at"])
        return InstrumentationHealth(**payload)

    async def purge_traces(self, query: TraceQuery) -> int:
        clauses: List[str] = []
        params: List = []
        for column, value in (("service_id", query.service_id), ("run_id", query.run_id),
                              ("pipeline_id", query.pipeline_id), ("query_id", query.query_id),
                              ("status", query.status), ("topology_hash", query.topology_hash)):
            if value is not None:
                params.append(value)
                clauses.append(f"{column} = ${len(params)}")
        if query.since is not None:
            params.append(query.since)
            clauses.append(f"timestamp >= ${len(params)}")
        if query.until is not None:
            params.append(query.until)
            clauses.append(f"timestamp <= ${len(params)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(f"DELETE FROM traces{where}", *params)
        return int(result.rsplit(" ", 1)[-1])

    async def get_query_lineage(self, query_id: str) -> Dict:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            forge_row = await conn.fetchrow(
                """SELECT q.query_id, q.text, q.scenario_id, q.query_type, q.difficulty_label,
                          q.failure_category, q.validated, q.positive_doc_ids_json, q.dataset_id,
                          s.scenario_type, s.evidence_summary
                   FROM forge_queries q
                   LEFT JOIN forge_scenarios s ON s.dataset_id = q.dataset_id AND s.scenario_id = q.scenario_id
                   WHERE q.query_id = $1 LIMIT 1""",
                query_id,
            )
            eval_rows = await conn.fetch(
                """SELECT rq.run_id, rq.query_text, rq.dataset_name, r.experiment_name, r.started_at
                   FROM run_queries rq JOIN runs r ON r.run_id = rq.run_id WHERE rq.query_id = $1
                   ORDER BY r.started_at DESC""",
                query_id,
            )

        origin: Dict = {"source": "dataset", "query_text": None, "dataset_name": None, "forge": None}
        if forge_row:
            fr = dict(forge_row)
            try:
                positive_doc_ids = json.loads(fr.pop("positive_doc_ids_json", "[]"))
            except Exception:
                positive_doc_ids = []
            origin = {
                "source": "forge",
                "query_text": fr.get("text"),
                "dataset_name": None,
                "forge": {
                    "dataset_id": fr.get("dataset_id"),
                    "scenario_id": fr.get("scenario_id"),
                    "scenario_type": fr.get("scenario_type"),
                    "query_type": fr.get("query_type"),
                    "difficulty_label": fr.get("difficulty_label"),
                    "failure_category": fr.get("failure_category"),
                    "validated": bool(fr.get("validated")),
                    "positive_doc_ids": positive_doc_ids,
                    "evidence_summary": fr.get("evidence_summary"),
                },
            }
        elif eval_rows:
            origin["query_text"] = eval_rows[0]["query_text"]
            origin["dataset_name"] = eval_rows[0]["dataset_name"]

        evaluations = []
        for row in eval_rows:
            er = dict(row)
            run_id = er["run_id"]
            metrics = await self.get_metrics(run_id)
            q_metrics = [m for m in metrics if m["query_id"] == query_id]
            diagnostics = await self.get_query_diagnostics(run_id, query_id=query_id)
            evaluations.append(
                {
                    "run_id": run_id,
                    "experiment_name": er.get("experiment_name"),
                    "started_at": str(er.get("started_at")),
                    "dataset_name": er.get("dataset_name"),
                    "metrics": q_metrics,
                    "diagnostics": diagnostics,
                }
            )

        match_difficulty = None
        match_failures: List[str] = []
        if forge_row:
            match_difficulty = forge_row["difficulty_label"]
            if forge_row["failure_category"]:
                match_failures = [forge_row["failure_category"]]
        elif evaluations and evaluations[0].get("diagnostics"):
            d0 = evaluations[0]["diagnostics"][0]
            match_difficulty = d0.get("difficulty_bucket")
            match_failures = list(d0.get("failure_labels") or [])

        production_traces = await self._categorical_trace_matches(match_difficulty, match_failures)

        return {
            "query_id": query_id,
            "origin": origin,
            "evaluations": evaluations,
            "production_matches": {
                "match_type": "categorical",
                "note": (
                    "Production queries are novel; traces are matched by predicted difficulty and "
                    "overlapping suspected failure labels, not by exact query_id."
                ),
                "match_difficulty": match_difficulty,
                "match_failure_labels": match_failures,
                "summary": {
                    "trace_count": len(production_traces),
                    "service_count": len({trace.get("service") for trace in production_traces}),
                    "failure_labels": sorted({label for trace in production_traces for label in trace.get("suspected_failures", [])}),
                },
                "traces": production_traces,
            },
        }

    async def _categorical_trace_matches(
        self,
        difficulty: Optional[str],
        failure_labels: List[str],
        limit: int = 50,
    ) -> List[Dict]:
        if not difficulty and not failure_labels:
            return []
        sql = "SELECT trace_json FROM traces WHERE run_id IS NULL ORDER BY timestamp DESC LIMIT $1"
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, limit * 5)
        matched = []
        label_set = set(failure_labels)
        for row in rows:
            trace = RetrievalTrace.from_dict(dict(row["trace_json"]))
            d = trace.to_dict()
            suspected = list(trace.metadata.get("suspected_failures", ()))
            predicted = trace.metadata.get("predicted_difficulty")
            if difficulty and predicted != difficulty:
                continue
            if label_set and not (label_set & set(suspected)):
                continue
            d["suspected_failures"] = suspected
            d["predicted_difficulty"] = predicted
            matched.append(d)
            if len(matched) >= limit:
                break
        return matched

    async def save_golden_set(self, name: str, queries_json: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO golden_sets (name, queries_json, created_at) VALUES ($1, $2, $3)
                   ON CONFLICT (name) DO UPDATE SET queries_json = EXCLUDED.queries_json,
                       created_at = EXCLUDED.created_at""",
                name,
                queries_json,
                datetime.now(timezone.utc),
            )

    async def get_golden_set(self, name: str) -> Optional[str]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT queries_json FROM golden_sets WHERE name = $1", name)
        return row["queries_json"] if row else None

    async def list_golden_sets(self) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, created_at FROM golden_sets ORDER BY created_at DESC")
        return [{"name": r["name"], "created_at": str(r["created_at"])} for r in rows]

    async def save_reliability_snapshot(self, run_id: str, value: float, components: Dict) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO reliability_snapshots (run_id, recorded_at, value, components_json) VALUES ($1, NOW(), $2, $3)",
                run_id,
                value,
                json.dumps(components),
            )

    async def get_reliability_history(self, run_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if run_id:
                rows = await conn.fetch(
                    "SELECT run_id, recorded_at, value, components_json FROM reliability_snapshots "
                    "WHERE run_id = $1 ORDER BY recorded_at DESC LIMIT $2",
                    run_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT run_id, recorded_at, value, components_json FROM reliability_snapshots "
                    "ORDER BY recorded_at DESC LIMIT $1",
                    limit,
                )
        out = []
        for r in rows:
            d = dict(r)
            d["recorded_at"] = str(d["recorded_at"])
            try:
                d["components"] = json.loads(d.pop("components_json", "{}"))
            except Exception:
                d["components"] = {}
            out.append(d)
        return out

    async def save_analysis_record(self, kind: str, record_id: str, payload: Dict, version: int = 1) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            current = await conn.fetchval(
                "SELECT MAX(version) FROM analysis_records WHERE kind=$1 AND record_id=$2",
                kind,
                record_id,
            )
            expected = int(current or 0) + 1
            if version != expected:
                raise ValueError(f"{kind} version must be {expected}")
            await conn.execute(
                "INSERT INTO analysis_records VALUES ($1,$2,$3,$4,$5)",
                kind,
                record_id,
                version,
                json.dumps(payload, sort_keys=True),
                datetime.now(timezone.utc),
            )

    async def get_analysis_record(self, kind: str, record_id: str) -> Dict | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload_json,version,created_at FROM analysis_records WHERE kind=$1 AND record_id=$2 ORDER BY version DESC LIMIT 1",
                kind,
                record_id,
            )
        if row is None:
            return None
        payload = row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"])
        return {**payload, "version": row["version"], "created_at": str(row["created_at"])}

    async def list_analysis_records(self, kind: str) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ON (record_id) record_id,payload_json,version,created_at FROM analysis_records WHERE kind=$1 ORDER BY record_id,version DESC",
                kind,
            )
        return [
            {
                **(row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"])),
                "record_id": row["record_id"],
                "version": row["version"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    async def save_cohort(self, cohort_id: str, payload: Dict, version: int) -> None:
        await self.save_analysis_record("cohort", cohort_id, payload, version)
    async def get_cohort(self, cohort_id: str) -> Dict | None:
        return await self.get_analysis_record("cohort", cohort_id)
    async def list_cohorts(self) -> List[Dict]:
        return await self.list_analysis_records("cohort")
    async def save_corpus_snapshot(self, snapshot_id: str, payload: Dict, version: int = 1) -> None:
        await self.save_analysis_record("corpus_snapshot", snapshot_id, payload, version)
    async def append_judgment(self, judgment_id: str, payload: Dict, version: int = 1) -> None:
        await self.save_analysis_record("judgment", judgment_id, payload, version)
    async def save_baseline(self, baseline_id: str, payload: Dict, version: int = 1) -> None:
        await self.save_analysis_record("baseline", baseline_id, payload, version)
    async def save_regression_check(self, check_id: str, payload: Dict, version: int = 1) -> None:
        await self.save_analysis_record("check", check_id, payload, version)
    async def append_alert(self, alert_id: str, payload: Dict, version: int = 1) -> None:
        await self.save_analysis_record("alert", alert_id, payload, version)

    @staticmethod
    def _trace_row_to_dict(d: Dict) -> Dict:
        if d.get("timestamp") is not None:
            d["timestamp"] = str(d["timestamp"])
        try:
            d["suspected_failures"] = json.loads(d.pop("suspected_failures_json", "[]"))
        except Exception:
            d["suspected_failures"] = []
        try:
            d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
        except Exception:
            d["metadata"] = {}
        return d
