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
    status TEXT,
    latency_ms REAL,
    retrieved_doc_ids_json TEXT,
    retrieved_scores_json TEXT,
    error_traceback TEXT
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
    value REAL
)
"""

_CREATE_CACHE = """
CREATE TABLE IF NOT EXISTS result_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
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
                snap.stage_index,
                result.status,
                snap.latency_ms,
                json.dumps([d.id for d in snap.documents]),
                json.dumps([d.score for d in snap.documents]),
                result.error_traceback,
            )
            for snap in result.snapshots
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO raw_results
                   (run_id, pipeline_id, query_id, stage_index, status,
                    latency_ms, retrieved_doc_ids_json, retrieved_scores_json, error_traceback)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
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
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO metric_scores
                   (run_id, pipeline_id, query_id, stage_index, metric_name, k, value)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                run_id, pipeline_id, query_id, stage_index, metric_name, k, value,
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
            for row in stage_rows:
                doc_ids = json.loads(row["retrieved_doc_ids_json"])
                scores = json.loads(row["retrieved_scores_json"])
                docs = [
                    Document(id=did, text="", score=s, rank=i + 1)
                    for i, (did, s) in enumerate(zip(doc_ids, scores))
                ]
                snapshots.append(
                    StageSnapshot(
                        stage_index=row["stage_index"],
                        stage_id=f"stage_{row['stage_index']}",
                        documents=docs,
                        latency_ms=row["latency_ms"],
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
                    total_latency_ms=total_latency,
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
        return [dict(row) for row in rows]

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
