from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiosqlite

from retrieval_observatory.types import Document, PipelineResult, StageSnapshot

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    experiment_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    config_json TEXT NOT NULL
)
"""

_CREATE_RAW_RESULTS = """
CREATE TABLE IF NOT EXISTS raw_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    retrieved_doc_ids_json TEXT NOT NULL,
    retrieved_scores_json TEXT NOT NULL,
    error_traceback TEXT
)
"""

_CREATE_METRIC_SCORES = """
CREATE TABLE IF NOT EXISTS metric_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    k INTEGER NOT NULL,
    value REAL NOT NULL
)
"""

_CREATE_CACHE = """
CREATE TABLE IF NOT EXISTS result_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
)
"""


class SQLiteStore:
    def __init__(self, db_path: str = ".retobs/results.db"):
        self.db_path = db_path

    async def init_db(self) -> None:
        import os
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(_CREATE_RUNS)
            await db.execute(_CREATE_RAW_RESULTS)
            await db.execute(_CREATE_METRIC_SCORES)
            await db.execute(_CREATE_CACHE)
            await db.commit()

    async def save_run(self, run_id: str, experiment_name: str, config_json: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO runs (run_id, experiment_name, started_at, config_json) VALUES (?, ?, ?, ?)",
                (run_id, experiment_name, datetime.now(timezone.utc).isoformat(), config_json),
            )
            await db.commit()

    async def finish_run(self, run_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE runs SET finished_at = ? WHERE run_id = ?",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
            await db.commit()

    async def save_result(self, run_id: str, result: PipelineResult) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            for snap in result.snapshots:
                doc_ids = json.dumps([d.id for d in snap.documents])
                scores = json.dumps([d.score for d in snap.documents])
                await db.execute(
                    """INSERT INTO raw_results
                       (run_id, pipeline_id, query_id, stage_index, status,
                        latency_ms, retrieved_doc_ids_json, retrieved_scores_json, error_traceback)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        result.pipeline_id,
                        result.query_id,
                        snap.stage_index,
                        result.status,
                        snap.latency_ms,
                        doc_ids,
                        scores,
                        result.error_traceback,
                    ),
                )
            await db.commit()

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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO metric_scores
                   (run_id, pipeline_id, query_id, stage_index, metric_name, k, value)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, pipeline_id, query_id, stage_index, metric_name, k, value),
            )
            await db.commit()

    async def get_results(self, run_id: str) -> List[PipelineResult]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM raw_results WHERE run_id = ? ORDER BY pipeline_id, query_id, stage_index",
                (run_id,),
            ) as cursor:
                rows = await cursor.fetchall()

        # Group rows into PipelineResult objects
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
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM metric_scores WHERE run_id = ?", (run_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def cache_get(self, cache_key: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT result_json FROM result_cache WHERE cache_key = ?", (cache_key,)
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None

    async def cache_set(self, cache_key: str, result_json: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO result_cache (cache_key, result_json) VALUES (?, ?)",
                (cache_key, result_json),
            )
            await db.commit()

    async def list_runs(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM runs ORDER BY started_at DESC") as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]
