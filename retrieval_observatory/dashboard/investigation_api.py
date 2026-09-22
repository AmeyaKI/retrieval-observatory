"""Investigation routes: thin HTTP wrappers over ``retrieval_observatory.evidence.service``."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.evidence.service import (
    InvestigationError,
    InvestigationRequest,
    build_projection,
    compare_investigations,
    inspect_document,
    inspect_investigation,
    inspect_query,
    resolve_scope,
)


def build_investigation_router(registry: DbRegistry) -> APIRouter:
    router = APIRouter(prefix="/dbs/{db_id}/investigation", tags=["investigation"])

    def store_for(db_id: str):
        try:
            return registry.get_store(db_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown database '{db_id}'")

    async def call(db_id: str, service: Callable[[Any, InvestigationRequest], Awaitable[Dict[str, Any]]], values: Dict[str, Any]) -> Dict[str, Any]:
        store = store_for(db_id)
        try:
            return await service(store, InvestigationRequest.from_mapping(values))
        except InvestigationError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "detail": error.detail})

    @router.get("/runs/{run_id}/queries")
    async def list_queries(db_id: str, run_id: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, inspect_investigation, {**request.query_params, "run_id": run_id, "view": "queries"})

    @router.get("/runs/{run_id}/queries/{query_id}")
    async def get_query(db_id: str, run_id: str, query_id: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, inspect_query, {**request.query_params, "run_id": run_id, "query_id": query_id})

    # Comparison: ``run_id`` is the candidate, ``against`` the baseline. ``pipeline``/``query`` are
    # accepted as short forms of ``pipeline_id``/``query_id``; a missing ``against`` is a 400.
    aliases = {"against": "comparison_run_id", "against_pipeline": "comparison_pipeline_id", "pipeline": "pipeline_id", "query": "query_id"}

    def compare_values(request: Request, **fixed: str) -> Dict[str, Any]:
        return {**{aliases.get(key, key): value for key, value in request.query_params.items()}, **fixed}

    @router.get("/runs/{run_id}/compare")
    async def compare(db_id: str, run_id: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, compare_investigations, compare_values(request, run_id=run_id))

    @router.get("/runs/{run_id}/compare/{query_id}")
    async def compare_query(db_id: str, run_id: str, query_id: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, compare_investigations, compare_values(request, run_id=run_id, query_id=query_id))

    @router.get("/runs/{run_id}/documents")
    async def list_documents(db_id: str, run_id: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, inspect_investigation, {**request.query_params, "run_id": run_id, "view": "documents"})

    @router.get("/runs/{run_id}/documents/{entity}")
    async def get_document(db_id: str, run_id: str, entity: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, inspect_document, {**request.query_params, "run_id": run_id, "entity": entity})

    async def projection_metadata(store: Any, request: InvestigationRequest) -> Dict[str, Any]:
        resolved = await resolve_scope(store, request)
        return await store.get_investigation_projection(resolved.store_scope()) or {"status": "unavailable"}

    @router.get("/runs/{run_id}/projection")
    async def get_projection(db_id: str, run_id: str, request: Request) -> Dict[str, Any]:
        return await call(db_id, projection_metadata, {**request.query_params, "run_id": run_id})

    async def build(store: Any, request: InvestigationRequest) -> Dict[str, Any]:
        resolved = await resolve_scope(store, request)
        return await build_projection(
            store, resolved.run_id, resolved.pipeline_id, resolved.spec, judgments=resolved.judgments, chunk_map=resolved.chunk_map
        )

    @router.post("/runs/{run_id}/projection")
    async def post_projection(db_id: str, run_id: str, body: Optional[Dict[str, Any]] = Body(default=None)) -> Dict[str, Any]:
        if registry.read_only:
            raise HTTPException(status_code=409, detail={"code": "read_only", "detail": "the registry is read-only"})
        return await call(db_id, build, {**(body or {}), "run_id": run_id})

    return router
