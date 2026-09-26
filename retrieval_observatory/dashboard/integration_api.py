"""Connect routes: the persisted integration verification records of one database (read-only)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.integrations.record import get_integration_record, list_integration_records
from retrieval_observatory.store.base import TraceQuery

#: Runs are scanned newest-first for the first one carrying the integration's pipeline.
_RUN_SCAN_LIMIT = 25
_SUMMARY_KEYS = ("integration_id", "service_id", "pipeline_id", "plan_id", "status", "depth", "verified_at", "version")


async def _first_run_for_pipeline(store: Any, pipeline_id: str) -> Optional[str]:
    for run in (await store.list_runs())[:_RUN_SCAN_LIMIT]:
        run_id = str(run["run_id"])
        manifest = await store.get_run_manifest(run_id) or {}
        listed = [str(p.get("id")) for p in ((manifest.get("normalized_config") or {}).get("pipelines") or []) if p.get("id")]
        if pipeline_id in listed:
            return run_id
        if not listed and await store.list_traces(TraceQuery(run_id=run_id, pipeline_id=pipeline_id, limit=1)):
            return run_id
    return None


def build_integration_router(registry: DbRegistry) -> APIRouter:
    router = APIRouter(prefix="/dbs/{db_id}/integrations", tags=["integrations"])

    def store_for(db_id: str):
        try:
            return registry.get_store(db_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown database '{db_id}'")

    @router.get("")
    async def list_integrations(db_id: str) -> Dict[str, Any]:
        records = await list_integration_records(store_for(db_id))
        summaries: List[Dict[str, Any]] = [{key: record.get(key) for key in _SUMMARY_KEYS} for record in records]
        return {"integrations": summaries}

    @router.get("/{integration_id:path}")
    async def get_integration(db_id: str, integration_id: str) -> Dict[str, Any]:
        store = store_for(db_id)
        record = await get_integration_record(store, integration_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"code": "integration_not_found", "detail": f"no verification record for {integration_id!r}"})
        run_id = await _first_run_for_pipeline(store, str(record["pipeline_id"]))
        return {**record, "investigation": {"run_id": run_id, "pipeline_id": record["pipeline_id"]} if run_id else None}

    return router
