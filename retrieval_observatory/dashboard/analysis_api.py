from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

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
from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.lineage_accounting import build_stage_loss_accounting
from retrieval_observatory.tracing.model import RetrievalTrace

_LINEAGE_OUTCOMES = (
    "relevant_retained",
    "irrelevant_removed",
    "irrelevant_retained",
    "relevant_lost_upstream",
    "relevant_dropped_at_stage",
    "unknown_relevance",
    "lineage_incomplete",
)


def _merge_counts(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for outcome in _LINEAGE_OUTCOMES:
        target[outcome] = int(target.get(outcome, 0)) + int(source.get(outcome, 0))
    target["unknown_relevance_count"] = target["unknown_relevance"]
    target["incomplete_lineage_count"] = target["lineage_incomplete"]


def build_query_lineage_payload(
    *,
    run_id: str,
    query_id: str,
    traces: Sequence[RetrievalTrace],
    qrels_for_query: Mapping[str, int],
    qrel_chunk_mapping_complete: bool,
) -> dict[str, Any]:
    trace_payloads = []
    nodes = []
    edges = []
    accounting: dict[str, Any] = {
        **{outcome: 0 for outcome in _LINEAGE_OUTCOMES},
        "unknown_relevance_count": 0,
        "incomplete_lineage_count": 0,
        "by_operator": {},
        "by_branch": {},
        "by_evidence": {},
    }
    findings = []
    warnings = []

    for trace in traces:
        graph = build_candidate_lineage(
            trace,
            qrels_for_query=qrels_for_query,
            qrel_chunk_mapping_complete=qrel_chunk_mapping_complete,
        )
        trace_accounting = build_stage_loss_accounting(graph)
        graph_payload = asdict(graph)
        accounting_payload = asdict(trace_accounting)
        trace_payloads.append(
            {
                "trace_id": trace.trace_id,
                "pipeline_id": trace.pipeline_id,
                "graph": graph_payload,
                "accounting": accounting_payload,
            }
        )
        _merge_counts(accounting, accounting_payload)
        for group_name in ("by_operator", "by_branch", "by_evidence"):
            for group_id, counts in accounting_payload[group_name].items():
                aggregate = accounting[group_name].setdefault(
                    group_id, {outcome: 0 for outcome in _LINEAGE_OUTCOMES}
                )
                _merge_counts(aggregate, counts)

        for candidate_id, passport in graph_payload["candidates"].items():
            node_id = f"{trace.trace_id}:{candidate_id}"
            nodes.append(
                {
                    **passport,
                    "node_id": node_id,
                    "trace_id": trace.trace_id,
                    "pipeline_id": trace.pipeline_id,
                }
            )
            if passport["lineage_evidence"] in {"partial", "unavailable"} or passport[
                "outcome"
            ]["kind"] == "lineage_incomplete":
                findings.append(
                    {
                        "code": "lineage_capture_partial",
                        "scope": "lineage_diagnosis",
                        "status": "BLOCK",
                        "observed": {
                            "trace_id": trace.trace_id,
                            "candidate_id": candidate_id,
                            "lineage_evidence": passport["lineage_evidence"],
                        },
                        "required": "recorded candidate path and exit evidence",
                        "detail": "Candidate lineage is incomplete for this trace.",
                        "next_action": "Capture complete operator inputs, outputs, and structured exits.",
                    }
                )
            if passport["lineage_evidence"] == "legacy_inferred" or passport["outcome"][
                "evidence"
            ] == "legacy_inferred":
                warnings.append(
                    {
                        "code": "legacy_lineage_inferred",
                        "trace_id": trace.trace_id,
                        "candidate_id": candidate_id,
                    }
                )
            if passport["relevance"]["kind"] == "unknown":
                warnings.append(
                    {
                        "code": "relevance_unavailable",
                        "trace_id": trace.trace_id,
                        "candidate_id": candidate_id,
                    }
                )
        for edge in graph_payload["edges"]:
            edges.append(
                {
                    **edge,
                    "trace_id": trace.trace_id,
                    "pipeline_id": trace.pipeline_id,
                    "source_node_id": f"{trace.trace_id}:{edge['source_candidate_id']}",
                    "target_node_id": f"{trace.trace_id}:{edge['target_candidate_id']}",
                }
            )
        if not graph_payload["candidates"]:
            findings.append(
                {
                    "code": "lineage_candidates_unavailable",
                    "scope": "lineage_diagnosis",
                    "status": "BLOCK",
                    "observed": {"trace_id": trace.trace_id, "candidate_count": 0},
                    "required": "at least one observed candidate",
                    "detail": "The trace contains no candidate lineage records.",
                    "next_action": "Capture candidate inputs and outputs for a representative query.",
                }
            )

    if qrels_for_query and not qrel_chunk_mapping_complete:
        warnings.append({"code": "qrel_to_chunk_mapping_unavailable"})
    return {
        "run_id": run_id,
        "query_id": query_id,
        "readiness": {
            "scope": "lineage_diagnosis",
            "status": "BLOCK" if findings else "READY",
            "findings": findings,
        },
        "evidence_warnings": warnings,
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "candidate_ids": [
                {
                    "trace_id": node["trace_id"],
                    "pipeline_id": node["pipeline_id"],
                    "candidate_id": node["candidate_id"],
                }
                for node in nodes
            ],
        },
        "accounting": accounting,
        "traces": trace_payloads,
    }


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
