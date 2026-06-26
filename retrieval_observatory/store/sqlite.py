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
    branch_id TEXT,
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
    branch_id TEXT,
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
_MIGRATE_RAW_RESULTS_BRANCH_ID = (
    "ALTER TABLE raw_results ADD COLUMN branch_id TEXT"
)
_MIGRATE_METRIC_SCORES_BRANCH_ID = (
    "ALTER TABLE metric_scores ADD COLUMN branch_id TEXT"
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

_CREATE_FORGE_DATASETS = """
CREATE TABLE IF NOT EXISTS forge_datasets (
    dataset_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    corpus_path TEXT NOT NULL DEFAULT '',
    output_dir TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL
)
"""

_CREATE_FORGE_SCENARIOS = """
CREATE TABLE IF NOT EXISTS forge_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    scenario_type TEXT NOT NULL,
    anchor_doc_ids_json TEXT NOT NULL,
    evidence_summary TEXT NOT NULL
)
"""

_CREATE_FORGE_QUERIES = """
CREATE TABLE IF NOT EXISTS forge_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    text TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    difficulty_label TEXT NOT NULL,
    failure_category TEXT,
    validated INTEGER NOT NULL DEFAULT 0,
    positive_doc_ids_json TEXT NOT NULL DEFAULT '[]'
)
"""
_CREATE_FORGE_QUERIES_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_forge_queries_dataset ON forge_queries(dataset_id)"
)

_CREATE_TRACES = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    query_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    status TEXT NOT NULL,
    total_latency_ms REAL NOT NULL,
    timestamp TEXT NOT NULL,
    predicted_difficulty TEXT,
    suspected_failures_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}'
)
"""
_CREATE_TRACES_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_traces_service_ts ON traces(service, timestamp)"
)

_CREATE_TRACE_STAGES = """
CREATE TABLE IF NOT EXISTS trace_stages (
    trace_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL,
    stage_id TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    candidate_count INTEGER NOT NULL,
    documents_json TEXT NOT NULL,
    PRIMARY KEY (trace_id, stage_index)
)
"""

_CREATE_GOLDEN_SETS = """
CREATE TABLE IF NOT EXISTS golden_sets (
    name TEXT PRIMARY KEY,
    queries_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_RELIABILITY_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS reliability_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    value REAL NOT NULL,
    components_json TEXT NOT NULL
)
"""


class SQLiteStore:
    def __init__(self, db_path: str = ".retobs/results.db"):
        self.db_path = db_path
        self._schema_ready = False

    async def _ensure_schema(self) -> None:
        """Create the schema on first use so callers never hit 'no such table'.

        All table DDL uses ``CREATE TABLE IF NOT EXISTS``, so this is idempotent and
        cheap. The flag avoids re-running migrations on every write.
        """
        if self._schema_ready:
            return
        await self.init_db()

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
            await db.execute(_CREATE_FORGE_DATASETS)
            await db.execute(_CREATE_FORGE_SCENARIOS)
            await db.execute(_CREATE_FORGE_QUERIES)
            await db.execute(_CREATE_FORGE_QUERIES_IDX)
            await db.execute(_CREATE_TRACES)
            await db.execute(_CREATE_TRACES_IDX)
            await db.execute(_CREATE_TRACE_STAGES)
            await db.execute(_CREATE_GOLDEN_SETS)
            await db.execute(_CREATE_RELIABILITY_SNAPSHOTS)
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
            try:
                await db.execute(_MIGRATE_RAW_RESULTS_BRANCH_ID)
            except Exception:
                pass
            try:
                await db.execute(_MIGRATE_METRIC_SCORES_BRANCH_ID)
            except Exception:
                pass
            await db.commit()
        self._schema_ready = True

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
                    candidate_count, branch_id, error_traceback)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            for snap in result.snapshots:
                doc_ids = json.dumps([d.id for d in snap.documents])
                scores = json.dumps([d.score for d in snap.documents])
                await db.execute(
                    """INSERT INTO raw_results
                       (run_id, pipeline_id, query_id, stage_index, stage_id, status,
                        latency_ms, retrieved_doc_ids_json, retrieved_scores_json, profiling_json,
                        candidate_count, branch_id, error_traceback)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        None,
                        result.error_traceback,
                    ),
                )
                for arm in snap.arms:
                    arm_doc_ids = json.dumps([d.id for d in arm.documents])
                    arm_scores = json.dumps([d.score for d in arm.documents])
                    await db.execute(
                        """INSERT INTO raw_results
                           (run_id, pipeline_id, query_id, stage_index, stage_id, status,
                            latency_ms, retrieved_doc_ids_json, retrieved_scores_json, profiling_json,
                            candidate_count, branch_id, error_traceback)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            run_id,
                            result.pipeline_id,
                            result.query_id,
                            snap.stage_index,
                            arm.stage_id,
                            result.status,
                            arm.latency_ms,
                            arm_doc_ids,
                            arm_scores,
                            json.dumps(arm.profiling),
                            arm.candidate_count or len(arm.documents),
                            arm.stage_id,
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
        branch_id: Optional[str] = None,
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
                    "branch_id": branch_id,
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
                   (run_id, pipeline_id, query_id, stage_index, metric_name, k, value, branch_id, query_metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            await db.commit()

    async def get_results(self, run_id: str) -> List[PipelineResult]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM raw_results WHERE run_id = ? ORDER BY pipeline_id, query_id, stage_index, COALESCE(branch_id, '')",
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
                branch_id = row["branch_id"] if "branch_id" in row.keys() else None
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

    async def save_forge_dataset(
        self,
        dataset_id: str,
        summary_json: str,
        corpus_path: str,
        output_dir: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO forge_datasets (dataset_id, created_at, corpus_path, output_dir, summary_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (dataset_id, datetime.now(timezone.utc).isoformat(), corpus_path, output_dir, summary_json),
            )
            await db.commit()

    async def get_forge_datasets(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT dataset_id, created_at, corpus_path, output_dir, summary_json FROM forge_datasets ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM forge_scenarios WHERE dataset_id = ?", (dataset_id,))
            for s in scenarios:
                await db.execute(
                    "INSERT INTO forge_scenarios (dataset_id, scenario_id, scenario_type, anchor_doc_ids_json, evidence_summary) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        dataset_id,
                        s.get("scenario_id", ""),
                        s.get("scenario_type", ""),
                        json.dumps(s.get("anchor_doc_ids", [])),
                        s.get("evidence_summary", ""),
                    ),
                )
            await db.commit()

    async def get_forge_scenarios(self, dataset_id: str) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT scenario_id, scenario_type, anchor_doc_ids_json, evidence_summary "
                "FROM forge_scenarios WHERE dataset_id = ?",
                (dataset_id,),
            ) as cursor:
                rows = await cursor.fetchall()
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM forge_queries WHERE dataset_id = ?", (dataset_id,))
            for q in queries:
                await db.execute(
                    "INSERT INTO forge_queries (dataset_id, query_id, text, scenario_id, query_type, "
                    "difficulty_label, failure_category, validated, positive_doc_ids_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        dataset_id,
                        q.get("query_id", ""),
                        q.get("text", ""),
                        q.get("scenario_id", ""),
                        q.get("query_type", ""),
                        q.get("difficulty_label", "medium"),
                        q.get("failure_category"),
                        1 if q.get("validated") else 0,
                        json.dumps(q.get("positive_doc_ids", [])),
                    ),
                )
            await db.commit()

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
        # scenario_type filter requires joining against the scenarios table by scenario_id
        where = ["q.dataset_id = ?"]
        params: List = [dataset_id]
        if difficulty:
            where.append("q.difficulty_label = ?")
            params.append(difficulty)
        if query_type:
            where.append("q.query_type = ?")
            params.append(query_type)
        if validated_only:
            where.append("q.validated = 1")
        join = ""
        if scenario_type:
            join = "JOIN forge_scenarios s ON s.dataset_id = q.dataset_id AND s.scenario_id = q.scenario_id"
            where.append("s.scenario_type = ?")
            params.append(scenario_type)
        sql = (
            "SELECT q.query_id, q.text, q.scenario_id, q.query_type, q.difficulty_label, "
            "q.failure_category, q.validated, q.positive_doc_ids_json "
            f"FROM forge_queries q {join} WHERE " + " AND ".join(where) +
            " ORDER BY q.id LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(params)) as cursor:
                rows = await cursor.fetchall()
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

    # ───────────────────────── TraceLens ─────────────────────────

    async def save_trace(self, trace) -> None:
        await self.save_traces_batch([trace])

    async def save_traces_batch(self, traces) -> None:
        await self._ensure_schema()
        async with aiosqlite.connect(self.db_path) as db:
            for t in traces:
                await db.execute(
                    "INSERT OR REPLACE INTO traces (trace_id, service, query_id, query_text, pipeline_id, "
                    "status, total_latency_ms, timestamp, predicted_difficulty, suspected_failures_json, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        t.trace_id, t.service, t.query_id, t.query_text, t.pipeline_id,
                        t.status, t.total_latency_ms, t.timestamp.isoformat(),
                        t.predicted_difficulty, json.dumps(t.suspected_failures),
                        json.dumps(t.metadata),
                    ),
                )
                await db.execute("DELETE FROM trace_stages WHERE trace_id = ?", (t.trace_id,))
                for s in t.snapshots:
                    docs = [
                        {"id": d.id, "text": getattr(d, "text", ""), "score": d.score,
                         "rank": d.rank, "title": getattr(d, "title", "")}
                        for d in s.documents
                    ]
                    await db.execute(
                        "INSERT INTO trace_stages (trace_id, stage_index, stage_id, latency_ms, candidate_count, documents_json) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (t.trace_id, s.stage_index, s.stage_id, s.latency_ms,
                         s.candidate_count or len(s.documents), json.dumps(docs)),
                    )
            await db.commit()

    async def list_services(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT service, COUNT(*) AS trace_count, MAX(timestamp) AS last_seen "
                "FROM traces GROUP BY service ORDER BY last_seen DESC"
            ) as cursor:
                rows = await cursor.fetchall()
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
        where = ["service = ?"]
        params: List = [service]
        if since:
            where.append("timestamp >= ?")
            params.append(since)
        if until:
            where.append("timestamp <= ?")
            params.append(until)
        if status:
            where.append("status = ?")
            params.append(status)
        if difficulty:
            where.append("predicted_difficulty = ?")
            params.append(difficulty)
        if suspected_only:
            where.append("suspected_failures_json != '[]'")
        sql = (
            "SELECT trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms, "
            "timestamp, predicted_difficulty, suspected_failures_json, metadata_json FROM traces WHERE "
            + " AND ".join(where) + " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(params)) as cursor:
                rows = await cursor.fetchall()
        return [self._trace_row_to_dict(dict(r)) for r in rows]

    async def get_trace(self, trace_id: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms, "
                "timestamp, predicted_difficulty, suspected_failures_json, metadata_json FROM traces WHERE trace_id = ?",
                (trace_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            d = self._trace_row_to_dict(dict(row))
            async with db.execute(
                "SELECT stage_index, stage_id, latency_ms, candidate_count, documents_json "
                "FROM trace_stages WHERE trace_id = ? ORDER BY stage_index",
                (trace_id,),
            ) as cursor:
                stage_rows = await cursor.fetchall()
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
        if service:
            where.append("service = ?")
            params.append(service)
        if older_than:
            where.append("timestamp < ?")
            params.append(older_than)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT trace_id FROM traces" + clause, tuple(params)) as cursor:
                ids = [r[0] for r in await cursor.fetchall()]
            await db.execute("DELETE FROM traces" + clause, tuple(params))
            if ids:
                qmarks = ",".join("?" for _ in ids)
                await db.execute(f"DELETE FROM trace_stages WHERE trace_id IN ({qmarks})", tuple(ids))
            await db.commit()
        return len(ids)

    async def save_reliability_snapshot(self, run_id: str, value: float, components: Dict) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO reliability_snapshots (run_id, recorded_at, value, components_json) VALUES (?, ?, ?, ?)",
                (run_id, datetime.now(timezone.utc).isoformat(), value, json.dumps(components)),
            )
            await db.commit()

    async def get_reliability_history(self, run_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        sql = "SELECT run_id, recorded_at, value, components_json FROM reliability_snapshots"
        params: List = []
        if run_id:
            sql += " WHERE run_id = ?"
            params.append(run_id)
        sql += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(params)) as cursor:
                rows = await cursor.fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["components"] = json.loads(d.pop("components_json", "{}"))
            except Exception:
                d["components"] = {}
            out.append(d)
        return out

    async def get_query_lineage(self, query_id: str) -> Dict:
        """Assemble one query's lifecycle across Forge, benchmarks, and production (categorical)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT q.query_id, q.text, q.scenario_id, q.query_type, q.difficulty_label, "
                "q.failure_category, q.validated, q.positive_doc_ids_json, q.dataset_id, "
                "s.scenario_type, s.evidence_summary "
                "FROM forge_queries q "
                "LEFT JOIN forge_scenarios s ON s.dataset_id = q.dataset_id AND s.scenario_id = q.scenario_id "
                "WHERE q.query_id = ? LIMIT 1",
                (query_id,),
            ) as cursor:
                forge_row = await cursor.fetchone()

            async with db.execute(
                "SELECT rq.run_id, rq.query_text, rq.dataset_name, r.experiment_name, r.started_at "
                "FROM run_queries rq JOIN runs r ON r.run_id = rq.run_id WHERE rq.query_id = ? "
                "ORDER BY r.started_at DESC",
                (query_id,),
            ) as cursor:
                eval_rows = await cursor.fetchall()

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
                    "started_at": er.get("started_at"),
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
        if difficulty:
            where.append("predicted_difficulty = ?")
            params.append(difficulty)
        sql = (
            "SELECT trace_id, service, query_id, query_text, pipeline_id, status, total_latency_ms, "
            "timestamp, predicted_difficulty, suspected_failures_json FROM traces"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit * 5)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(params)) as cursor:
                rows = await cursor.fetchall()
        matched = []
        label_set = set(failure_labels)
        for row in rows:
            d = dict(row)
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO golden_sets (name, queries_json, created_at) VALUES (?, ?, ?)",
                (name, queries_json, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_golden_set(self, name: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT queries_json FROM golden_sets WHERE name = ?", (name,)) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None

    async def list_golden_sets(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT name, created_at FROM golden_sets ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _trace_row_to_dict(d: Dict) -> Dict:
        try:
            d["suspected_failures"] = json.loads(d.pop("suspected_failures_json", "[]"))
        except Exception:
            d["suspected_failures"] = []
        try:
            d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
        except Exception:
            d["metadata"] = {}
        return d
