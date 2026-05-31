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
    stage_id TEXT,
    status TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    retrieved_doc_ids_json TEXT NOT NULL,
    retrieved_scores_json TEXT NOT NULL,
    profiling_json TEXT,
    candidate_count INTEGER DEFAULT 0,
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
    value REAL NOT NULL,
    query_metadata_json TEXT DEFAULT NULL
)
"""

# Migration: add query_metadata_json to existing databases that predate this column.
_MIGRATE_METRIC_SCORES_METADATA = (
    "ALTER TABLE metric_scores ADD COLUMN query_metadata_json TEXT DEFAULT NULL"
)
_MIGRATE_RAW_RESULTS_STAGE_ID = (
    "ALTER TABLE raw_results ADD COLUMN stage_id TEXT"
)
_MIGRATE_RAW_RESULTS_PROFILING = (
    "ALTER TABLE raw_results ADD COLUMN profiling_json TEXT"
)
_MIGRATE_RAW_RESULTS_CANDIDATE_COUNT = (
    "ALTER TABLE raw_results ADD COLUMN candidate_count INTEGER DEFAULT 0"
)

_CREATE_RUN_MANIFESTS = """
CREATE TABLE IF NOT EXISTS run_manifests (
    run_id TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
)
"""

_CREATE_VALIDATION_REPORTS = """
CREATE TABLE IF NOT EXISTS validation_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    config_path TEXT,
    created_at TEXT NOT NULL,
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

_CREATE_CACHE = """
CREATE TABLE IF NOT EXISTS result_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
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
            await db.execute(_CREATE_RUN_MANIFESTS)
            await db.execute(_CREATE_VALIDATION_REPORTS)
            await db.execute(_CREATE_QUERY_DIAGNOSTICS)
            await db.execute(_CREATE_RUN_QUERIES)
            # Best-effort migration for existing DBs (errors if column already exists)
            try:
                await db.execute(_MIGRATE_METRIC_SCORES_METADATA)
            except Exception:
                pass
            try:
                await db.execute(_MIGRATE_RAW_RESULTS_STAGE_ID)
            except Exception:
                pass
            try:
                await db.execute(_MIGRATE_RAW_RESULTS_PROFILING)
            except Exception:
                pass
            try:
                await db.execute(_MIGRATE_RAW_RESULTS_CANDIDATE_COUNT)
            except Exception:
                pass
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
            await db.execute(
                """INSERT INTO raw_results
                   (run_id, pipeline_id, query_id, stage_index, stage_id, status,
                    latency_ms, retrieved_doc_ids_json, retrieved_scores_json, profiling_json,
                    candidate_count, error_traceback)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            for snap in result.snapshots:
                doc_ids = json.dumps([d.id for d in snap.documents])
                scores = json.dumps([d.score for d in snap.documents])
                await db.execute(
                    """INSERT INTO raw_results
                       (run_id, pipeline_id, query_id, stage_index, stage_id, status,
                        latency_ms, retrieved_doc_ids_json, retrieved_scores_json, profiling_json,
                        candidate_count, error_traceback)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        result.pipeline_id,
                        result.query_id,
                        snap.stage_index,
                        snap.stage_id,
                        result.status,
                        snap.latency_ms,
                        doc_ids,
                        scores,
                        json.dumps(snap.profiling),
                        snap.candidate_count or len(snap.documents),
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                """INSERT INTO metric_scores
                   (run_id, pipeline_id, query_id, stage_index, metric_name, k, value, query_metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
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
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM metric_scores WHERE run_id = ?", (run_id,)
            ) as cursor:
                rows = await cursor.fetchall()
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

    async def save_run_manifest(self, run_id: str, manifest: Dict) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO run_manifests (run_id, manifest_json) VALUES (?, ?)",
                (run_id, json.dumps(manifest, sort_keys=True)),
            )
            await db.commit()

    async def get_run_manifest(self, run_id: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT manifest_json FROM run_manifests WHERE run_id = ?", (run_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def save_validation_report(
        self,
        report: Dict,
        config_path: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO validation_reports
                   (run_id, config_path, created_at, report_json)
                   VALUES (?, ?, ?, ?)""",
                (
                    run_id,
                    config_path,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(report),
                ),
            )
            await db.commit()

    async def save_query_diagnostics(self, rows: List[Dict]) -> None:
        if not rows:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                """INSERT OR REPLACE INTO query_diagnostics
                   (run_id, query_id, pipeline_id, difficulty_bucket, failure_labels_json,
                    missing_relevant_ids_json, stage_hits_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
            await db.commit()

    async def get_query_diagnostics(self, run_id: str, query_id: Optional[str] = None) -> List[Dict]:
        sql = "SELECT * FROM query_diagnostics WHERE run_id = ?"
        params: tuple = (run_id,)
        if query_id is not None:
            sql += " AND query_id = ?"
            params = (run_id, query_id)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                """INSERT OR REPLACE INTO run_queries
                   (run_id, query_id, query_text, dataset_name)
                   VALUES (?, ?, ?, ?)""",
                [
                    (run_id, q.query_id, q.text, dataset_name)
                    for q in queries
                ],
            )
            await db.commit()

    async def get_run_queries(self, run_id: str) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM run_queries WHERE run_id = ?", (run_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_runs_for_dataset(self, dataset_name: str) -> List[Dict]:
        """Return finished runs whose config dataset.name matches (normalized)."""
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
        """Distinct (run_id, query_id, difficulty_bucket) from diagnostics."""
        if not run_ids:
            return []
        placeholders = ",".join("?" for _ in run_ids)
        sql = f"""
            SELECT run_id, query_id, difficulty_bucket
            FROM query_diagnostics
            WHERE run_id IN ({placeholders})
              AND difficulty_bucket != 'unknown'
            GROUP BY run_id, query_id, difficulty_bucket
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, run_ids) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]
