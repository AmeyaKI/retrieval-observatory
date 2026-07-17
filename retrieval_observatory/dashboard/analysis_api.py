from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query

from retrieval_observatory.analysis.branches import analyze_branches
from retrieval_observatory.analysis.cohorts import CohortClause, CohortDefinition, validate_cohort
from retrieval_observatory.analysis.corpus_health import analyze_corpus_health
from retrieval_observatory.analysis.gates import analyze_gates
from retrieval_observatory.analysis.ground_truth import analyze_ground_truth
from retrieval_observatory.analysis.instrumentation import analyze_instrumentation
from retrieval_observatory.analysis.latency import analyze_latency
from retrieval_observatory.analysis.scores import analyze_scores
from retrieval_observatory.analysis.service import cohort_from_record, filter_traces, make_scope
from retrieval_observatory.store.base import TraceQuery


def build_analysis_router(store_for: Callable[[str], Any]) -> APIRouter:
    router = APIRouter(prefix="/dbs/{db_id}/analysis", tags=["analysis"])

    async def context(
        db_id: str,
        service_id: str | None,
        run_id: str | None,
        since: datetime | None,
        until: datetime | None,
        cohort_id: str | None,
    ):
        store = store_for(db_id)
        cohort = None
        if cohort_id:
            record = await store.get_analysis_record("cohort", cohort_id)
            if record is None:
                raise HTTPException(422, f"Unknown cohort '{cohort_id}'")
            cohort = cohort_from_record({**record, "cohort_id": cohort_id})
        traces = await store.list_traces(
            TraceQuery(service_id=service_id, run_id=run_id, since=since, until=until, limit=100000)
        )
        return store, filter_traces(traces, cohort), make_scope(db_id, service_id, run_id, since, until, cohort_id)

    async def inputs(
        db_id: str,
        service_id: str | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cohort_id: str | None = None,
    ):
        return await context(db_id, service_id, run_id, since, until, cohort_id)

    @router.get("/gates")
    async def gates(
        db_id: str,
        service_id: str | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cohort_id: str | None = None,
    ):
        store, traces, scope = await inputs(db_id, service_id, run_id, since, until, cohort_id)
        qrels = await store.get_qrels(run_id) if run_id else {}
        route_labels = {
            trace.query_id: str(trace.metadata["expected_route"])
            for trace in traces
            if trace.metadata.get("expected_route")
        }
        return analyze_gates(traces, qrels, route_labels, scope).to_dict()

    @router.get("/branches")
    async def branches(
        db_id: str,
        service_id: str | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cohort_id: str | None = None,
    ):
        store, traces, scope = await inputs(db_id, service_id, run_id, since, until, cohort_id)
        return analyze_branches(traces, await store.get_qrels(run_id) if run_id else {}, scope).to_dict()

    @router.get("/scores")
    async def scores(
        db_id: str,
        service_id: str | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cohort_id: str | None = None,
    ):
        store, traces, scope = await inputs(db_id, service_id, run_id, since, until, cohort_id)
        return analyze_scores(traces, await store.get_qrels(run_id) if run_id else {}, scope).to_dict()

    @router.get("/latency")
    async def latency(
        db_id: str,
        service_id: str | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cohort_id: str | None = None,
    ):
        _, traces, scope = await inputs(db_id, service_id, run_id, since, until, cohort_id)
        return analyze_latency(traces, scope).to_dict()

    @router.get("/corpus-health")
    async def corpus_health(db_id: str, run_id: str | None = None, cohort_id: str | None = None):
        store, _, scope = await inputs(db_id, None, run_id, cohort_id=cohort_id)
        snapshots = await store.list_analysis_records("corpus_snapshot")
        return analyze_corpus_health(
            snapshots[0] if snapshots else None, snapshots[1] if len(snapshots) > 1 else None, scope
        ).to_dict()

    @router.get("/ground-truth")
    async def ground_truth(db_id: str, run_id: str = Query(...), cohort_id: str | None = None):
        store, _, scope = await inputs(db_id, None, run_id, cohort_id=cohort_id)
        return analyze_ground_truth(
            await store.get_qrels(run_id),
            await store.get_run_queries(run_id),
            await store.list_analysis_records("judgment"),
            scope,
        ).to_dict()

    @router.get("/instrumentation")
    async def instrumentation(
        db_id: str,
        service_id: str = Query(...),
        since: datetime | None = None,
        until: datetime | None = None,
        cohort_id: str | None = None,
    ):
        store, traces, scope = await inputs(db_id, service_id, None, since, until, cohort_id)
        return analyze_instrumentation(
            None, traces, await store.get_instrumentation_health(service_id), scope
        ).to_dict()

    @router.post("/cohorts")
    async def save_cohort(db_id: str, body: dict[str, Any]):
        try:
            definition = CohortDefinition(
                str(body["cohort_id"]),
                str(body["name"]),
                int(body.get("version", 1)),
                tuple(CohortClause(**item) for item in body["clauses"]),
                body.get("conjunction", "all"),
            )
            validate_cohort(definition)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        await store_for(db_id).save_analysis_record(
            "cohort", definition.cohort_id, definition.to_dict(), definition.version
        )
        return definition.to_dict()

    @router.get("/cohorts")
    async def list_cohorts(db_id: str):
        return await store_for(db_id).list_analysis_records("cohort")

    durable_kinds = {"corpus_snapshot", "judgment", "baseline", "check", "alert"}

    @router.post("/records/{kind}/{record_id}")
    async def save_record(db_id: str, kind: str, record_id: str, body: dict[str, Any]):
        if kind not in durable_kinds:
            raise HTTPException(422, f"Unsupported analysis record kind '{kind}'")
        version = int(body.get("version", 1))
        await store_for(db_id).save_analysis_record(kind, record_id, body, version)
        return {"kind": kind, "record_id": record_id, "version": version}

    @router.get("/records/{kind}")
    async def list_records(db_id: str, kind: str):
        if kind not in durable_kinds:
            raise HTTPException(422, f"Unsupported analysis record kind '{kind}'")
        return await store_for(db_id).list_analysis_records(kind)

    return router
