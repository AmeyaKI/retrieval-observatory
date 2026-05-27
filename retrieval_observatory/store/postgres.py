from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
    error_traceback TEXT
)
"""

_MIGRATE_RAW_RESULTS_STAGE_ID = "ALTER TABLE raw_results ADD COLUMN stage_id TEXT"
_MIGRATE_RAW_RESULTS_PROFILING = "ALTER TABLE raw_results ADD COLUMN profiling_json TEXT"
_MIGRATE_RAW_RESULTS_CANDIDATE_COUNT = "ALTER TABLE raw_results ADD COLUMN candidate_count INT DEFAULT 0"

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
    query_metadata_json TEXT DEFAULT NULL
)
"""

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
            await conn.execute(_CREATE_VALIDATION_REPORTS)
            await conn.execute(_CREATE_QUERY_DIAGNOSTICS)
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
                result.error_traceback,
            )
        ]
        rows.extend(
            [
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
                    result.error_traceback,
                )
                for snap in result.snapshots
            ]
        )
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO raw_results
                   (run_id, pipeline_id, query_id, stage_index, stage_id, status,
                    latency_ms, retrieved_doc_ids_json, retrieved_scores_json, profiling_json,
                    candidate_count, error_traceback)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                rows,
            )

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
        metadata_json = json.dumps(query_metadata) if query_metadata else None
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
                    "query_metadata_json": metadata_json,
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
                   (run_id, pipeline_id, query_id, stage_index, metric_name, k, value, query_metadata_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                [
                    (
                        row["run_id"],
                        row["pipeline_id"],
                        row["query_id"],
                        row["stage_index"],
                        row["metric_name"],
                        row["k"],
                        row["value"],
                        json.dumps(row["query_metadata_json"]) if row.get("query_metadata_json") else None,
                    )
                    for row in rows
                ],
            )

    async def get_results(self, run_id: str) -> List[PipelineResult]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM raw_results WHERE run_id = $1 ORDER BY pipeline_id, query_id, stage_index",
                run_id,
            )

        grouped: Dict[tuple, list] = {}
        for row in rows:
            key = (row["pipeline_id"], row["query_id"])
            grouped.setdefault(key, []).append(row)

        results = []
        for (pipeline_id, query_id), stage_rows in grouped.items():
            snapshots = []
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
                snapshots.append(
                    StageSnapshot(
                        stage_index=row["stage_index"],
                        stage_id=row["stage_id"] or f"stage_{row['stage_index']}",
                        documents=docs,
                        latency_ms=row["latency_ms"],
                        profiling=json.loads(row["profiling_json"] or "{}"),
                        candidate_count=row["candidate_count"] or len(docs),
                    )
                )
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
