from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    experiment_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    config_json TEXT NOT NULL
)
"""

_CREATE_RAW_RESULTS = """
CREATE TABLE IF NOT EXISTS raw_results (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    pipeline_id TEXT,
    query_id TEXT,
    stage_index INT,
    stage_id TEXT,
    status TEXT,
    latency_ms REAL,
    retrieved_doc_ids_json TEXT,
    retrieved_scores_json TEXT,
    profiling_json TEXT,
    candidate_count INT DEFAULT 0,
    branch_id TEXT,
    error_traceback TEXT
)
"""

_MIGRATE_RAW_RESULTS_STAGE_ID = "ALTER TABLE raw_results ADD COLUMN stage_id TEXT"
_MIGRATE_RAW_RESULTS_PROFILING = "ALTER TABLE raw_results ADD COLUMN profiling_json TEXT"
_MIGRATE_RAW_RESULTS_CANDIDATE_COUNT = "ALTER TABLE raw_results ADD COLUMN candidate_count INT DEFAULT 0"
_MIGRATE_RAW_RESULTS_BRANCH_ID = "ALTER TABLE raw_results ADD COLUMN branch_id TEXT"

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

_CREATE_CACHE = """
CREATE TABLE IF NOT EXISTS result_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
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
    PRIMARY KEY (run_id, query_id, pipeline_id)
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
    positive_doc_ids_json TEXT NOT NULL DEFAULT '[]'
)
"""

_CREATE_TRACES = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    query_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    status TEXT NOT NULL,
    total_latency_ms REAL NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    predicted_difficulty TEXT,
    suspected_failures_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}'
)
"""

_CREATE_TRACE_STAGES = """
CREATE TABLE IF NOT EXISTS trace_stages (
    trace_id TEXT NOT NULL,
    stage_index INT NOT NULL,
    stage_id TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    candidate_count INT NOT NULL,
    documents_json TEXT NOT NULL,
    PRIMARY KEY (trace_id, stage_index)
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

_CREATE_TRACES_V2 = """
CREATE TABLE IF NOT EXISTS traces_v2 (
    trace_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    trace_json TEXT NOT NULL
)
"""

_CREATE_TRACES_V2_IDX = "CREATE INDEX IF NOT EXISTS idx_traces_v2_run ON traces_v2(run_id, query_id)"
_CREATE_TRACES_V2_PIPELINE_IDX = "CREATE INDEX IF NOT EXISTS idx_traces_v2_pipeline ON traces_v2(pipeline_id)"
_CREATE_TRACES_V2_STATUS_IDX = "CREATE INDEX IF NOT EXISTS idx_traces_v2_status ON traces_v2(status)"

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
            await conn.execute(_CREATE_RAW_RESULTS)
            await conn.execute(_CREATE_METRIC_SCORES)
            await conn.execute(_CREATE_CACHE)
            await conn.execute(_CREATE_RUN_MANIFESTS)
            await conn.execute(_CREATE_RUN_QRELS)
            await conn.execute(_CREATE_VALIDATION_REPORTS)
            await conn.execute(_CREATE_QUERY_DIAGNOSTICS)
            await conn.execute(_CREATE_RUN_QUERIES)
            await conn.execute(_CREATE_FORGE_DATASETS)
            await conn.execute(_CREATE_FORGE_SCENARIOS)
            await conn.execute(_CREATE_FORGE_QUERIES)
            await conn.execute(_CREATE_TRACES)
            await conn.execute(_CREATE_TRACE_STAGES)
            await conn.execute(_CREATE_GOLDEN_SETS)
            await conn.execute(_CREATE_RELIABILITY_SNAPSHOTS)
            await conn.execute(_CREATE_TRACES_V2)
            await conn.execute(_CREATE_TRACES_V2_IDX)
            await conn.execute(_CREATE_TRACES_V2_PIPELINE_IDX)
            await conn.execute(_CREATE_TRACES_V2_STATUS_IDX)
            await conn.execute(_CREATE_DOC_EDGES)
            await conn.execute(_CREATE_DOC_EDGES_SRC_IDX)
            await conn.execute(_CREATE_DOC_EDGES_DST_IDX)
            try:
                await conn.execute(_MIGRATE_RAW_RESULTS_STAGE_ID)
            except Exception:
                pass
            try:
                await conn.execute(_MIGRATE_RAW_RESULTS_PROFILING)
            except Exception:
                pass
            try:
                await conn.execute(_MIGRATE_RAW_RESULTS_CANDIDATE_COUNT)
            except Exception:
                pass
            try:
                await conn.execute(_MIGRATE_RAW_RESULTS_BRANCH_ID)
            except Exception:
                pass
            try:
                await conn.execute(_MIGRATE_METRIC_SCORES_BRANCH_ID)
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

    async def save_result(self, run_id: str, result: PipelineResult) -> None:
        pool = await self._get_pool()
        rows = [
            (
                run_id,
                result.pipeline_id,
                result.query_id,
                -1,
                "__pipeline__",
                result.status,
                result.total_latency_ms,
                "[]",
                "[]",
                "{}",
                0,
                None,
                result.error_traceback,
            )
        ]
        for snap in result.snapshots:
            rows.append(
                (
                    run_id,
                    result.pipeline_id,
                    result.query_id,
                    snap.stage_index,
                    snap.stage_id,
                    result.status,
                    snap.latency_ms,
                    json.dumps([d.id for d in snap.documents]),
                    json.dumps([d.score for d in snap.documents]),
                    json.dumps(snap.profiling),
                    snap.candidate_count or len(snap.documents),
                    None,
                    result.error_traceback,
                )
            )
            for arm in snap.arms:
                rows.append(
                    (
                        run_id,
                        result.pipeline_id,
                        result.query_id,
                        snap.stage_index,
                        arm.stage_id,
                        result.status,
                        arm.latency_ms,
                        json.dumps([d.id for d in arm.documents]),
                        json.dumps([d.score for d in arm.documents]),
                        json.dumps(arm.profiling),
                        arm.candidate_count or len(arm.documents),
                        arm.stage_id,
                        result.error_traceback,
                    )
                )
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO raw_results
                   (run_id, pipeline_id, query_id, stage_index, stage_id, status,
                    latency_ms, retrieved_doc_ids_json, retrieved_scores_json, profiling_json,
                    candidate_count, branch_id, error_traceback)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)""",
                rows,
            )

    async def save_trace_v2(self, trace: RetrievalTraceV2) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO traces_v2
                   (trace_id, run_id, query_id, pipeline_id, status, timestamp, trace_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (trace_id) DO UPDATE SET
                       run_id = EXCLUDED.run_id,
                       query_id = EXCLUDED.query_id,
                       pipeline_id = EXCLUDED.pipeline_id,
                       status = EXCLUDED.status,
                       timestamp = EXCLUDED.timestamp,
                       trace_json = EXCLUDED.trace_json""",
                trace.trace_id,
                trace.run_id,
                trace.query_id,
                trace.pipeline_id,
                trace.status,
                trace.timestamp,
                json.dumps(trace.to_dict()),
            )

    async def get_trace_v2(self, trace_id: str) -> Optional[RetrievalTraceV2]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT trace_json FROM traces_v2 WHERE trace_id = $1", trace_id)
        if not row:
            return None
        return RetrievalTraceV2.from_dict(json.loads(row["trace_json"]))

    async def get_traces_v2(self, run_id: str) -> List[RetrievalTraceV2]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT trace_json FROM traces_v2 WHERE run_id = $1 ORDER BY timestamp", run_id)
        return [RetrievalTraceV2.from_dict(json.loads(row["trace_json"])) for row in rows]

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

    async def get_results(self, run_id: str) -> List[PipelineResult]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM raw_results WHERE run_id = $1 ORDER BY pipeline_id, query_id, stage_index, COALESCE(branch_id, '')",
                run_id,
            )

        grouped: Dict[tuple, list] = {}
        for row in rows:
            key = (row["pipeline_id"], row["query_id"])
            grouped.setdefault(key, []).append(row)

        results = []
        for (pipeline_id, query_id), stage_rows in grouped.items():
            snapshots = []
            snap_by_stage: Dict[int, StageSnapshot] = {}
            status = "OK"
            error_traceback = None
            total_latency = 0.0
            envelope_latency = None
            for row in stage_rows:
                if row["stage_index"] == -1 and row["stage_id"] == "__pipeline__":
                    status = row["status"]
                    error_traceback = row["error_traceback"]
                    envelope_latency = row["latency_ms"]
                    continue
                doc_ids = json.loads(row["retrieved_doc_ids_json"])
                scores = json.loads(row["retrieved_scores_json"])
                docs = [
                    Document(id=did, text="", score=s, rank=i + 1)
                    for i, (did, s) in enumerate(zip(doc_ids, scores))
                ]
                branch_id = row.get("branch_id")
                snapshot = StageSnapshot(
                    stage_index=row["stage_index"],
                    stage_id=row["stage_id"] or f"stage_{row['stage_index']}",
                    documents=docs,
                    latency_ms=row["latency_ms"],
                    profiling=json.loads(row["profiling_json"] or "{}"),
                    candidate_count=row["candidate_count"] or len(docs),
                )
                if branch_id:
                    parent = snap_by_stage.get(row["stage_index"])
                    if parent is not None:
                        parent.arms.append(snapshot)
                    continue
                snapshots.append(snapshot)
                snap_by_stage[row["stage_index"]] = snapshot
                total_latency += row["latency_ms"]
                status = row["status"]
                error_traceback = row["error_traceback"]
            results.append(
                PipelineResult(
                    query_id=query_id,
                    pipeline_id=pipeline_id,
                    snapshots=snapshots,
                    total_latency_ms=envelope_latency if envelope_latency is not None else total_latency,
                    status=status,
                    error_traceback=error_traceback,
                )
            )
        return results

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
                "SELECT status, COUNT(*) AS n FROM traces_v2 WHERE run_id = $1 GROUP BY status",
                run_id,
            )
        if rows:
            for row in rows:
                counts[str(row["status"])] = int(row["n"])
            return counts

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM raw_results WHERE run_id = $1 AND stage_index = -1 GROUP BY status",
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
                    missing_relevant_ids_json, stage_hits_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (run_id, query_id, pipeline_id) DO UPDATE SET
                       difficulty_bucket = EXCLUDED.difficulty_bucket,
                       failure_labels_json = EXCLUDED.failure_labels_json,
                       missing_relevant_ids_json = EXCLUDED.missing_relevant_ids_json,
                       stage_hits_json = EXCLUDED.stage_hits_json""",
                [
                    (
                        row["run_id"],
                        row["query_id"],
                        row["pipeline_id"],
                        row["difficulty_bucket"],
                        json.dumps(row.get("failure_labels", [])),
                        json.dumps(row.get("missing_relevant_ids", [])),
                        json.dumps(row.get("stage_hits", {})),
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
            result.append(item)
        return result

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
                d["summary"] = json.loads(d.pop("summary_json", "{}"))
            except Exception:
                d["summary"] = {}
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
                        failure_category, validated, positive_doc_ids_json)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    dataset_id,
                    q.get("query_id", ""),
                    q.get("text", ""),
                    q.get("scenario_id", ""),
                    q.get("query_type", ""),
                    q.get("difficulty_label", "medium"),
                    q.get("failure_category"),
                    1 if q.get("validated") else 0,
                    json.dumps(q.get("positive_doc_ids", [])),
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
            "q.failure_category, q.validated, q.positive_doc_ids_json "
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
            result.append(d)
        return result

    async def save_trace(self, trace) -> None:
        await self.save_traces_batch([trace])

    async def save_traces_batch(self, traces) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for t in traces:
                await conn.execute(
                    """INSERT INTO traces
                       (trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms,
                        timestamp, predicted_difficulty, suspected_failures_json, metadata_json)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                       ON CONFLICT (trace_id) DO UPDATE SET
                           service = EXCLUDED.service,
                           status = EXCLUDED.status,
                           total_latency_ms = EXCLUDED.total_latency_ms,
                           timestamp = EXCLUDED.timestamp,
                           predicted_difficulty = EXCLUDED.predicted_difficulty,
                           suspected_failures_json = EXCLUDED.suspected_failures_json,
                           metadata_json = EXCLUDED.metadata_json""",
                    t.trace_id,
                    t.service,
                    t.query_id,
                    t.query_text,
                    t.pipeline_id,
                    t.status,
                    t.total_latency_ms,
                    t.timestamp,
                    t.predicted_difficulty,
                    json.dumps(t.suspected_failures),
                    json.dumps(t.metadata),
                )
                await conn.execute("DELETE FROM trace_stages WHERE trace_id = $1", t.trace_id)
                for s in t.snapshots:
                    docs = [
                        {
                            "id": d.id,
                            "text": getattr(d, "text", ""),
                            "score": d.score,
                            "rank": d.rank,
                            "title": getattr(d, "title", ""),
                        }
                        for d in s.documents
                    ]
                    await conn.execute(
                        """INSERT INTO trace_stages
                           (trace_id, stage_index, stage_id, latency_ms, candidate_count, documents_json)
                           VALUES ($1, $2, $3, $4, $5, $6)""",
                        t.trace_id,
                        s.stage_index,
                        s.stage_id,
                        s.latency_ms,
                        s.candidate_count or len(s.documents),
                        json.dumps(docs),
                    )

    async def list_services(self) -> List[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT service, COUNT(*) AS trace_count, MAX(timestamp) AS last_seen
                   FROM traces GROUP BY service ORDER BY last_seen DESC"""
            )
        return [dict(r) for r in rows]

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
        where = ["service = $1"]
        params: List = [service]
        idx = 2
        if since:
            where.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1
        if until:
            where.append(f"timestamp <= ${idx}")
            params.append(until)
            idx += 1
        if status:
            where.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if difficulty:
            where.append(f"predicted_difficulty = ${idx}")
            params.append(difficulty)
            idx += 1
        if suspected_only:
            where.append("suspected_failures_json != '[]'")
        sql = (
            "SELECT trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms, "
            "timestamp, predicted_difficulty, suspected_failures_json, metadata_json FROM traces WHERE "
            + " AND ".join(where)
            + f" ORDER BY timestamp DESC LIMIT ${idx} OFFSET ${idx + 1}"
        )
        params.extend([limit, offset])
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._trace_row_to_dict(dict(r)) for r in rows]

    async def get_trace(self, trace_id: str) -> Optional[Dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms,
                          timestamp, predicted_difficulty, suspected_failures_json, metadata_json
                   FROM traces WHERE trace_id = $1""",
                trace_id,
            )
            if not row:
                return None
            d = self._trace_row_to_dict(dict(row))
            stage_rows = await conn.fetch(
                """SELECT stage_index, stage_id, latency_ms, candidate_count, documents_json
                   FROM trace_stages WHERE trace_id = $1 ORDER BY stage_index""",
                trace_id,
            )
        stages = []
        for sr in stage_rows:
            sd = dict(sr)
            try:
                sd["documents"] = json.loads(sd.pop("documents_json", "[]"))
            except Exception:
                sd["documents"] = []
            stages.append(sd)
        d["stages"] = stages
        return d

    async def purge_traces(self, service: Optional[str] = None, older_than: Optional[str] = None) -> int:
        where = []
        params: List = []
        idx = 1
        if service:
            where.append(f"service = ${idx}")
            params.append(service)
            idx += 1
        if older_than:
            where.append(f"timestamp < ${idx}")
            params.append(older_than)
            idx += 1
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT trace_id FROM traces{clause}", *params)
            ids = [r["trace_id"] for r in rows]
            await conn.execute(f"DELETE FROM traces{clause}", *params)
            if ids:
                await conn.execute("DELETE FROM trace_stages WHERE trace_id = ANY($1::text[])", ids)
        return len(ids)

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
        where = []
        params: List = []
        idx = 1
        if difficulty:
            where.append(f"predicted_difficulty = ${idx}")
            params.append(difficulty)
            idx += 1
        sql = (
            "SELECT trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms, "
            "timestamp, predicted_difficulty, suspected_failures_json FROM traces"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY timestamp DESC LIMIT ${idx}"
        params.append(limit * 5)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        matched = []
        label_set = set(failure_labels)
        for row in rows:
            d = dict(row)
            d["timestamp"] = str(d.get("timestamp"))
            try:
                suspected = json.loads(d.pop("suspected_failures_json", "[]"))
            except Exception:
                suspected = []
            if label_set and not (label_set & set(suspected)):
                continue
            d["suspected_failures"] = suspected
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
