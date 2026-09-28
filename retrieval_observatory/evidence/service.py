"""Investigation service: the one implementation behind the HTTP, MCP, SDK and CLI surfaces.

Store-agnostic and free of transport types. GET-shaped functions (``inspect_*``) never write;
``build_projection`` is the explicit indexing step that materialises journey rows through
``store.replace_investigation_projection``. Every store call is scoped by run, pipeline and
evaluation digest so two runs can never share rows.
"""

from __future__ import annotations

import json

from collections import Counter
from dataclasses import dataclass, fields, replace
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Iterable, Literal, Mapping, Sequence, get_args

from retrieval_observatory.datasets.judgments import ChunkMap, EvaluationSpec, EvaluationUnit, JudgmentSet, query_input_identity
from retrieval_observatory.evidence.investigation import (
    DERIVATION_VERSION,
    CaptureState,
    JourneyRow,
    JudgmentState,
    Membership,
    Outcome,
)
from retrieval_observatory.evidence.journeys import project_trace_journeys, summarize_journeys, summarize_pair_counts, summarize_stages
from retrieval_observatory.store.base import (
    INVESTIGATION_PAGE_LIMIT,
    INVESTIGATION_SORT_KEYS,
    InvestigationFilter,
    InvestigationPage,
    InvestigationScope,
    TraceDecodeError,
    TraceQuery,
    clamp_page_limit,
    decode_cursor,
    encode_cursor,
)
from retrieval_observatory.tracing.lineage_diff import Alignment, align_stages, diff_journeys, summarize_journey_diff
from retrieval_observatory.tracing.model import RetrievalTrace

View = Literal["queries", "documents"]
_VOCABULARY: dict[str, tuple[str, ...]] = {
    "unit": get_args(EvaluationUnit),
    "view": get_args(View),
    "outcome": get_args(Outcome),
    "judgment": get_args(JudgmentState),
    "capture_state": get_args(CaptureState),
    "final_membership": get_args(Membership),
}
_PROJECTION_ACTION = "POST /dbs/{db_id}/investigation/runs/{run_id}/projection or `retobs storage index RUN`"


class InvestigationError(Exception):
    """400 invalid request, 404 not found, 409 write refused, 422 unsupported value or unreadable stored trace."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


async def _list_traces(store: Any, query: TraceQuery) -> list[RetrievalTrace]:
    """``store.list_traces`` with a stored trace that does not decode as a coded 422 naming it."""
    try:
        return await store.list_traces(query)
    except TraceDecodeError as error:
        raise InvestigationError(422, "trace_unreadable", f"{error}; delete or re-ingest trace {error.trace_id!r}") from error


def _finding(code: str, detail: str, action: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "action": action}


def _int(name: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise InvestigationError(422, "invalid_value", f"{name} must be an integer")


def split_entity(entity: str) -> tuple[str, str]:
    """``"namespace:entity_id"`` or a bare id in the ``default`` namespace."""
    namespace, sep, entity_id = entity.partition(":")
    return (namespace, entity_id) if sep else ("default", entity)


@dataclass(frozen=True)
class InvestigationRequest:
    run_id: str
    pipeline_id: str | None = None
    boundary: str = "final_retrieval"
    unit: EvaluationUnit = "document"
    k: int | None = None
    relevance_threshold: int = 1
    view: View = "queries"
    query_id: str | None = None
    trace_id: str | None = None
    entity: str | None = None
    stage_id: str | None = None
    outcome: str | None = None
    judgment: str | None = None
    capture_state: str | None = None
    final_membership: str | None = None
    limit: int = 50
    cursor: str | None = None
    # Comparison (``compare_investigations``): the baseline run (URL key ``against``) and its pipeline
    # (URL key ``against_pipeline``; defaults to the candidate's resolved pipeline).
    comparison_run_id: str | None = None
    comparison_pipeline_id: str | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> InvestigationRequest:
        supported = [f.name for f in fields(cls)]
        unknown = sorted(set(values) - set(supported))
        if unknown:
            raise InvestigationError(400, "unknown_parameter", f"unsupported parameter(s) {unknown}; supported: {supported}")
        kwargs = {name: value for name, value in values.items() if value is not None}
        if not kwargs.get("run_id"):
            raise InvestigationError(400, "run_id_required", "run_id is required")
        for name, allowed in _VOCABULARY.items():
            if name in kwargs and kwargs[name] not in allowed:
                raise InvestigationError(422, "unsupported_value", f"{name} must be one of {list(allowed)}")
        kwargs["limit"] = clamp_page_limit(_int("limit", kwargs.get("limit", 50)))
        for name in ("k", "relevance_threshold"):
            if name in kwargs:
                kwargs[name] = _int(name, kwargs[name])
                if kwargs[name] < 1:
                    raise InvestigationError(422, "unsupported_value", f"{name} must be >= 1")
        return cls(**kwargs)

    def filters(self, **extra: str | None) -> InvestigationFilter:
        namespace = entity_id = None
        if self.entity and not self.entity.endswith("*"):
            namespace, entity_id = split_entity(self.entity)
        return InvestigationFilter(
            query_id=self.query_id,
            trace_id=self.trace_id,
            namespace=namespace,
            entity_id=entity_id,
            outcome=self.outcome,
            judgment=self.judgment,
            final_membership=self.final_membership,
            capture_state=self.capture_state,
            loss_boundary=self.stage_id,
            **extra,
        )


@dataclass(frozen=True)
class ResolvedScope:
    run_id: str
    pipeline_id: str
    spec: EvaluationSpec
    judgments: JudgmentSet
    chunk_map: ChunkMap | None
    evaluation_digest: str
    judgment_digest: str
    manifest: dict
    findings: list[dict]

    def store_scope(self) -> InvestigationScope:
        return InvestigationScope(self.run_id, self.pipeline_id, self.evaluation_digest)


async def resolve_scope(store: Any, request: InvestigationRequest) -> ResolvedScope:
    run_id = request.run_id
    if not any(run.get("run_id") == run_id for run in await store.list_runs()):
        raise InvestigationError(404, "run_not_found", f"run {run_id!r} not found")
    manifest = await store.get_run_manifest(run_id) or {}
    config = manifest.get("normalized_config") or {}
    findings: list[dict] = []

    pipelines = [str(p["id"]) for p in config.get("pipelines") or [] if p.get("id")]
    if request.pipeline_id is not None:
        pipeline_id = request.pipeline_id
        if pipeline_id not in pipelines and pipeline_id not in await store.list_pipeline_ids(run_id):
            raise InvestigationError(404, "pipeline_not_found", f"pipeline {pipeline_id!r} not found in run {run_id!r}")
    else:
        if not pipelines:  # no manifest listing (legacy/production runs, graph-only configs): the traces' pipeline ids
            pipelines = await store.list_pipeline_ids(run_id)
        if len(pipelines) == 1:
            pipeline_id = pipelines[0]
        elif not pipelines:
            raise InvestigationError(404, "pipeline_not_found", f"run {run_id!r} has no traces")
        else:
            raise InvestigationError(422, "pipeline_required", f"run {run_id!r} has pipelines {pipelines}; pass pipeline_id")

    k = request.k
    if k is None:
        recorded = (manifest.get("evaluation") or {}).get("k")
        cutoffs = (config.get("metrics") or {}).get("recall_at_k") or []
        k = int(recorded) if recorded else (int(max(cutoffs)) if cutoffs else 10)
        findings.append(_finding("k_defaulted", f"k defaulted to {k}", "pass k to evaluate at another cutoff"))
    spec = EvaluationSpec(unit=request.unit, relevance_threshold=request.relevance_threshold, boundary=request.boundary, k=k)

    records = manifest.get("judgment_records")
    if records:
        judgments = JudgmentSet.from_records(records)
    else:
        judgments = JudgmentSet.from_qrels(await store.get_qrels(run_id), namespace="default")
    if not len(judgments):
        findings.append(_finding("judgments_unavailable", "no relevance judgments for this run", "movement is inspectable; outcomes stay unjudged"))
    elif spec.unit == "chunk" and all(record.get("unit", "document") == "document" for record in records or ()):
        findings.append(
            _finding(
                "judgments_not_inherited",
                "the run's judgments are document-level; at unit=chunk a document's judgment is not inherited by its chunks, so every chunk reads unjudged",
                "use unit=document to judge each chunk through its document",
            )
        )
    triples = manifest.get("chunk_map")
    chunk_map = ChunkMap.from_pairs([tuple(triple) for triple in triples]) if triples else None
    return ResolvedScope(run_id, pipeline_id, spec, judgments, chunk_map, spec.digest(), judgments.digest(), manifest, findings)


def _run_payload(rows: Sequence[JourneyRow], traces: Sequence[RetrievalTrace]) -> dict:
    return {
        **summarize_journeys(rows),
        "queries_with_traces": len({trace.query_id for trace in traces}),
        "trace_count": len(traces),
    }


def _summaries(rows: Sequence[JourneyRow], traces: Sequence[RetrievalTrace], query_text: Mapping[str, str | None]) -> list[dict]:
    run = _run_payload(rows, traces)
    summaries: list[dict] = [{"kind": "run", "key": "summary", "payload": run}]
    by_query: dict[str, list[JourneyRow]] = {}
    relevant_queries: dict[str, set[str]] = {}
    for row in rows:
        by_query.setdefault(row.query_id, []).append(row)
        if row.judgment == "relevant":
            relevant_queries.setdefault(f"{row.namespace}:{row.entity_id}", set()).add(row.query_id)
    for query_id, counts in run["by_query"].items():
        own = by_query[query_id]
        payload = {
            **counts,
            "query_text": query_text.get(query_id),
            "insufficient": sum(row.outcome == "insufficient_evidence" for row in own),
            "capture_partial": sum(row.capture_state == "partial" for row in own),
            "relevant_delivered": counts["TP"],
            "relevant_missed": counts["FN"],
            "unjudged_included": sum(row.judgment in ("unjudged", "unmapped") and row.final_membership == "included" for row in own),
            "unknown_capture": sum(row.capture_state == "partial" or row.final_membership == "unknown" for row in own),
            "loss_boundaries": dict(Counter(row.loss_boundary for row in own if row.loss_boundary is not None)),
            "trace_ids": sorted({row.trace_id for row in own}),
        }
        summaries.append({"kind": "query", "key": query_id, "payload": payload})
    for key, counts in run["by_entity"].items():
        payload = {**counts, "judged_relevant_queries": sorted(relevant_queries.get(key, ()))}
        summaries.append({"kind": "document", "key": key, "payload": payload})
    operator_of = {span.op_id: str(span.operator_id) for trace in traces for span in trace.spans}
    for op_id, counts in summarize_stages(traces)["by_op_id"].items():
        summaries.append({"kind": "stage", "key": op_id, "payload": {**counts, "operator_id": operator_of[op_id]}})
    return summaries


async def build_projection(
    store: Any,
    run_id: str,
    pipeline_id: str,
    spec: EvaluationSpec,
    *,
    judgments: JudgmentSet,
    chunk_map: ChunkMap | None,
) -> dict:
    """EXPLICIT WRITE: project every trace of run+pipeline and replace the stored projection."""
    if getattr(store, "read_only", False):
        raise InvestigationError(409, "read_only", "the store is read-only; index from a writable process")
    traces = await _list_traces(store, TraceQuery(run_id=run_id, pipeline_id=pipeline_id))
    digests = {"evaluation_digest": spec.digest(), "judgment_digest": judgments.digest()}
    rows = [row for trace in traces for row in project_trace_journeys(trace, judgments, spec, chunk_map=chunk_map, **digests)]
    get_run_queries = getattr(store, "get_run_queries", None)
    queries = await get_run_queries(run_id) if get_run_queries is not None else []
    query_text = {str(query["query_id"]): query.get("query_text") for query in queries}
    scope = InvestigationScope(run_id, pipeline_id, digests["evaluation_digest"])
    try:
        await store.replace_investigation_projection(
            scope,
            rows=[row.to_dict() for row in rows],
            summaries=_summaries(rows, traces, query_text),
            derivation_version=DERIVATION_VERSION,
            judgment_digest=digests["judgment_digest"],
            trace_count=len(traces),
        )
    except RuntimeError as error:  # investigation tables unavailable (pre-v3 file)
        raise InvestigationError(409, "read_only", str(error))
    except Exception as error:  # e.g. a read-only file or a full disk; the store's rebuild is one transaction
        raise InvestigationError(409, "projection_write_failed", f"projection not written: {error}") from error
    return await store.get_investigation_projection(scope)


async def _projection_state(store: Any, resolved: ResolvedScope) -> tuple[dict | None, str, list[dict]]:
    meta = await store.get_investigation_projection(resolved.store_scope())
    if meta is None or meta.get("status") != "complete":
        findings = [_finding("projection_unavailable", "no complete projection for this scope", _PROJECTION_ACTION)]
        recorded = (resolved.manifest.get("investigation_projection") or {}).get(resolved.pipeline_id) or {}
        if recorded.get("status") == "failed":  # the run's own projection write failed; say why
            findings.append(_finding("projection_failed", f"the run's projection write failed: {recorded.get('error')}", recorded.get("repair") or _PROJECTION_ACTION))
        return None, "unavailable", findings
    if meta.get("derivation_version") != DERIVATION_VERSION or meta.get("judgment_digest") != resolved.judgment_digest:
        return meta, "partial", [_finding("projection_stale", "projection predates the current derivation or judgments", _PROJECTION_ACTION)]
    return meta, "ready", []


async def _page(call: Callable[..., Awaitable[InvestigationPage]], *args: Any, **kwargs: Any) -> InvestigationPage:
    try:
        return await call(*args, **kwargs)
    except ValueError as error:  # malformed cursor
        raise InvestigationError(400, "invalid_cursor", str(error))


async def _all_rows(store: Any, scope: InvestigationScope, filters: InvestigationFilter, order: str) -> list[dict]:
    rows: list[dict] = []
    cursor = None
    while True:
        page = await _page(store.list_investigation_pairs, scope, filters, limit=INVESTIGATION_PAGE_LIMIT, cursor=cursor, order=order)
        rows.extend(page.rows)
        cursor = page.next_cursor
        if cursor is None:
            return rows


def _summary(payload: Mapping[str, Any] | None) -> dict | None:
    if payload is None:
        return None
    return {key: value for key, value in payload.items() if key not in ("by_query", "by_entity")}


def _summarize(rows: Sequence[dict]) -> dict:
    return _summary(summarize_journeys([JourneyRow.from_dict(row) for row in rows])) or {}


async def _summarize_matching(store: Any, scope: InvestigationScope, filters: InvestigationFilter, order: str) -> dict:
    """``_summarize`` over every pair matching ``filters``, from one store read of the counted columns."""
    facts = await store.list_investigation_pair_facts(scope, filters, order=order)
    return summarize_pair_counts([SimpleNamespace(**fact) for fact in facts], sum(fact["events"] for fact in facts))


def _stages(trace: RetrievalTrace) -> list[dict]:
    counts = summarize_stages([trace])["by_op_id"]
    return [
        {
            "op_id": span.op_id,
            "operator_id": str(span.operator_id),
            "invocation_id": span.invocation_id,
            "op_type": span.op_type,
            "status": span.status,
            "branch": span.branch_id,
            "parent_ids": list(span.parent_ids),
            "input_capture": span.input_capture,
            "output_capture": span.output_capture,
            "received": counts[span.op_id]["candidates_received"],
            "emitted": len(span.outputs),
            "removed": counts[span.op_id]["removal_events"],
            "introduced": counts[span.op_id]["introduced"],
            "source_ref": span.source_ref,
            "params": _json_params(span.params),
            "gate_values": dict(span.gate_values),
            "error": span.error,
        }
        for span in trace.spans
    ]


def _json_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Recorded configuration for the stage panel: JSON-safe, bounded to scalars and short containers."""
    out: dict[str, Any] = {}
    for key, value in list(params.items())[:50]:
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
        elif isinstance(value, (list, tuple, dict)):
            out[str(key)] = value if len(json.dumps(value, default=str)) <= 2000 else "<omitted: too large>"
        else:
            out[str(key)] = f"<{type(value).__name__}>"
    return out


def _envelope(
    resolved: ResolvedScope,
    request: InvestigationRequest,
    *,
    projection: str,
    rows: list[dict],
    total: int | None,
    next_cursor: str | None,
    run_payload: Mapping[str, Any] | None,
    summary: dict | None,
    stages: list[dict] | None,
    findings: list[dict],
    rows_kind: str | None = None,
) -> dict:
    scope = {
        "run_id": resolved.run_id,
        "pipeline_id": resolved.pipeline_id,
        "boundary": resolved.spec.boundary,
        "unit": resolved.spec.unit,
        "k": resolved.spec.k,
        "relevance_threshold": resolved.spec.relevance_threshold,
        "evaluation_digest": resolved.evaluation_digest,
        "judgment_digest": resolved.judgment_digest,
    }
    for name in ("query_id", "trace_id", "entity"):
        if getattr(request, name) is not None:
            scope[name] = getattr(request, name)
    if rows_kind is not None:
        scope["rows_kind"] = rows_kind
    partial = sum(row.get("capture_state") == "partial" for row in rows)
    payload = run_payload or {}
    return {
        "schema_version": 1,
        "scope": scope,
        "capabilities": {
            "projection": projection,
            "judgments": "ready" if len(resolved.judgments) else "unavailable",
            "capture": {"complete_rows": len(rows) - partial, "partial_rows": partial},
        },
        "coverage": {
            "queries_attempted": (resolved.manifest.get("counts") or {}).get("attempted"),
            "queries_with_traces": payload.get("queries_with_traces"),
            "queries_projected": len(payload["by_query"]) if "by_query" in payload else None,
            "pairs": payload.get("pairs"),
            "events": payload.get("events"),
        },
        "rows": rows,
        "total": total,
        "next_cursor": next_cursor,
        "summary": summary,
        "stages": stages,
        "findings": findings,
    }


async def _run_payload_stored(store: Any, scope: InvestigationScope) -> dict | None:
    stored = await store.get_investigation_summary(scope, "run", "summary")
    return None if stored is None else stored["payload"]


async def _stored_stages(store: Any, scope: InvestigationScope) -> list[dict]:
    """The stored per-operator aggregates (``summarize_stages`` counts plus ``operator_id``), keyed by op_id."""
    page = await _page(store.list_investigation_summaries, scope, "stage", limit=INVESTIGATION_PAGE_LIMIT)
    return [{"op_id": row["key"], **row["payload"]} for row in page.rows]


async def inspect_investigation(store: Any, request: InvestigationRequest) -> dict:
    """The queries or documents list for one scope; never scans traces."""
    resolved = await resolve_scope(store, request)
    meta, state, findings = await _projection_state(store, resolved)
    findings = [*resolved.findings, *findings]
    if meta is None:
        return _envelope(resolved, request, projection=state, rows=[], total=None, next_cursor=None, run_payload=None, summary=None, stages=None, findings=findings)
    scope = resolved.store_scope()
    run_payload = await _run_payload_stored(store, scope)
    stages = await _stored_stages(store, scope)
    if request.view == "documents":
        prefix = request.entity[:-1] if request.entity and request.entity.endswith("*") else None
        page = await _page(store.list_investigation_summaries, scope, "document", limit=request.limit, cursor=request.cursor, key_prefix=prefix)
        rows = [{"entity": row["key"], **row["payload"]} for row in page.rows]
        summary = _summary(run_payload)
        rows_kind = "document_summaries"
    else:
        filters = request.filters()
        prefix = request.query_id[:-1] if request.query_id and request.query_id.endswith("*") else None
        # A pair-level filter (anything but a `query_id` prefix) lists the matching pairs; otherwise the
        # stored per-query summaries, whose counts cover every pair of each query rather than one page.
        filtered = any(getattr(filters, f.name) is not None for f in fields(filters) if f.name != "query_id") or (request.query_id is not None and prefix is None)
        if filtered:
            page = await _page(store.list_investigation_pairs, scope, filters, limit=request.limit, cursor=request.cursor, order="priority")
            rows = page.rows
            summary = await _summarize_matching(store, scope, filters, "priority")
            rows_kind = "pairs"
            findings.append(_finding("filtered_pairs", "rows are the candidate pairs matching the filters; counts reflect matching pairs, not whole queries", "clear the filters for the per-query summaries"))
        else:
            page = await _page(store.list_investigation_summaries, scope, "query", limit=request.limit, cursor=request.cursor, key_prefix=prefix)
            rows = [{"query_id": row["key"], **row["payload"]} for row in page.rows]
            summary = _summary(run_payload)
            rows_kind = "query_summaries"
    return _envelope(resolved, request, projection=state, rows=rows, total=page.total, next_cursor=page.next_cursor, run_payload=run_payload, summary=summary, stages=stages, findings=findings, rows_kind=rows_kind)


def _matches(row: Mapping[str, Any], filters: InvestigationFilter) -> bool:
    return all(getattr(filters, f.name) is None or row.get(f.name) == getattr(filters, f.name) for f in fields(filters))


def _project(traces: Sequence[RetrievalTrace], resolved: ResolvedScope) -> list[JourneyRow]:
    """The rows ``build_projection`` would store for ``traces``, computed in memory (never written)."""
    return [
        row
        for trace in traces
        for row in project_trace_journeys(
            trace, resolved.judgments, resolved.spec, chunk_map=resolved.chunk_map,
            evaluation_digest=resolved.evaluation_digest, judgment_digest=resolved.judgment_digest,
        )
    ]


async def _scope_payload(
    store: Any, resolved: ResolvedScope, meta: Mapping[str, Any] | None, traces: Sequence[RetrievalTrace]
) -> tuple[list[JourneyRow] | None, dict | None]:
    """(rows projected in memory, run payload): the stored run summary when a projection exists (no
    rows), otherwise ``traces`` projected with the same judgments, chunk map and spec."""
    if meta is not None:
        return None, await _run_payload_stored(store, resolved.store_scope())
    projected = _project(traces, resolved)
    return projected, _run_payload(projected, traces)


async def _pairs(
    store: Any,
    resolved: ResolvedScope,
    request: InvestigationRequest,
    projected: Sequence[JourneyRow] | None,
    *,
    order: str,
) -> tuple[list[dict], int, str | None, dict]:
    """(rows, total, next_cursor, summary) for the pairs matching ``request``.

    The stored projection when ``projected`` is ``None``; otherwise ``projected`` (from
    ``_scope_payload``) in the store's order. Every single-scope surface reads pairs here.
    """
    filters = request.filters()
    if projected is None:
        scope = resolved.store_scope()
        page = await _page(store.list_investigation_pairs, scope, filters, limit=request.limit, cursor=request.cursor, order=order)
        return page.rows, page.total, page.next_cursor, await _summarize_matching(store, scope, filters, order)
    rows = sorted((row.to_dict() for row in projected), key=lambda row: tuple(row[key] for key in INVESTIGATION_SORT_KEYS[order]))
    rows = [row for row in rows if _matches(row, filters)]
    return rows, len(rows), None, _summarize(rows)


def _resolve_entity(entity: str, resolved: ResolvedScope, keys: Iterable[str]) -> tuple[str, dict | None]:
    """``namespace:entity_id`` for an entity handle. A bare id is the one scope entity ``keys`` entry
    with that id (several is ``entity_ambiguous``). Otherwise, at document unit, a chunk id the run's
    chunk map knows (bare, or ``namespace:chunk_id``) names its document, exactly as the projection groups it."""
    if ":" not in entity:
        matches = sorted(key for key in keys if key.partition(":")[2] == entity)
        if len(matches) > 1:
            raise InvestigationError(422, "entity_ambiguous", f"entity {entity!r} is in several namespaces {matches}; pass namespace:{entity}")
        if matches:
            detail = f"bare id {entity} is {matches[0]}, the only namespace with rows for it in this scope"
            return matches[0], _finding("entity_resolved", detail, "pass namespace:entity_id to name the namespace")
    namespace, entity_id = split_entity(entity)
    chunk_map = resolved.chunk_map
    if resolved.spec.unit == "document" and chunk_map is not None:
        for chunk in (chunk_map.chunk_ref(entity), *((chunk_map.chunk_ref(entity_id, namespace),) if ":" in entity else ())):
            document = chunk_map.document_for(chunk)
            if document is not None:
                resolved_entity = f"{document.namespace}:{document.entity_id}"
                detail = f"chunk {chunk.namespace}:{chunk.entity_id} counts as document {resolved_entity} through the run's chunk map"
                return resolved_entity, _finding("entity_resolved", detail, "rows are the document's; pass unit=chunk for the chunk itself")
    return f"{namespace}:{entity_id}", None


async def inspect_query(store: Any, request: InvestigationRequest) -> dict:
    """One query's rows, its summary, and the selected trace's stages (from spans, not rows)."""
    if not request.query_id:
        raise InvestigationError(400, "query_id_required", "query_id is required")
    resolved = await resolve_scope(store, request)
    traces = await _list_traces(store, TraceQuery(run_id=resolved.run_id, pipeline_id=resolved.pipeline_id, query_id=request.query_id))
    if not traces:
        raise InvestigationError(404, "query_not_found", f"no traces for query {request.query_id!r} in run {resolved.run_id!r} pipeline {resolved.pipeline_id!r}")
    meta, state, findings = await _projection_state(store, resolved)
    findings = [*resolved.findings, *findings]

    if request.trace_id is not None:
        selected = next((trace for trace in traces if trace.trace_id == request.trace_id), None)
        if selected is None:
            raise InvestigationError(404, "trace_not_found", f"trace {request.trace_id!r} not found for query {request.query_id!r}")
    elif len(traces) == 1:
        selected = traces[0]
    else:
        selected = None
        findings.append(_finding("multiple_traces", f"query has {len(traces)} traces; rows carry trace_id", "pass trace_id to select one"))

    projected, run_payload = await _scope_payload(store, resolved, meta, traces)
    rows, total, next_cursor, summary = await _pairs(store, resolved, request, projected, order="priority")
    stages = _stages(selected) if selected is not None else None
    return _envelope(resolved, request, projection=state, rows=rows, total=total, next_cursor=next_cursor, run_payload=run_payload, summary=summary, stages=stages, findings=findings, rows_kind="pairs")


async def inspect_document(store: Any, request: InvestigationRequest) -> dict:
    """One evaluation entity across every query of the scope."""
    if not request.entity or request.entity.endswith("*"):
        raise InvestigationError(400, "entity_required", "entity is required as 'namespace:entity_id' or a bare id")
    resolved = await resolve_scope(store, request)
    meta, state, findings = await _projection_state(store, resolved)
    traces = () if meta is not None else await _list_traces(store, TraceQuery(run_id=resolved.run_id, pipeline_id=resolved.pipeline_id))
    projected, run_payload = await _scope_payload(store, resolved, meta, traces)
    keys = (run_payload or {}).get("by_entity") or {}
    entity, resolution = _resolve_entity(request.entity, resolved, keys)
    findings = [*resolved.findings, *findings, *((resolution,) if resolution else ())]
    if entity not in keys:
        raise InvestigationError(404, "entity_not_found", f"entity {entity} has no rows in this scope")
    request = replace(request, entity=entity)
    rows, total, next_cursor, summary = await _pairs(store, resolved, request, projected, order="entity")
    return _envelope(resolved, request, projection=state, rows=rows, total=total, next_cursor=next_cursor, run_payload=run_payload, summary=summary, stages=None, findings=findings, rows_kind="pairs")


# ---------------------------------------------------------------------------
# Comparison: the candidate run's journeys against a baseline run's, under one evaluation spec
# ---------------------------------------------------------------------------


def _comparison_filters(request: InvestigationRequest) -> InvestigationFilter:
    """Only the selectors that mean the same thing in both runs (query and entity; never trace ids)."""
    own = request.filters()
    return InvestigationFilter(query_id=own.query_id, namespace=own.namespace, entity_id=own.entity_id)


async def _comparison_rows(store: Any, resolved: ResolvedScope, request: InvestigationRequest) -> tuple[list[dict], str, list[dict]]:
    """One side's rows: the stored projection, else (single query only) an on-the-fly projection."""
    meta, state, findings = await _projection_state(store, resolved)
    filters = _comparison_filters(request)
    if meta is not None:
        return await _all_rows(store, resolved.store_scope(), filters, "priority"), state, findings
    findings = [_finding("projection_unavailable", f"no complete projection for run {resolved.run_id!r} pipeline {resolved.pipeline_id!r}", _PROJECTION_ACTION)]
    if request.query_id is None:
        return [], state, findings
    traces = await _list_traces(store, TraceQuery(run_id=resolved.run_id, pipeline_id=resolved.pipeline_id, query_id=request.query_id))
    projected = [row.to_dict() for row in _project(traces, resolved)]
    return [row for row in projected if _matches(row, filters)], state, findings


async def _query_alignment(store: Any, baseline_run_id: str, candidate_run_id: str) -> dict[str, Alignment]:
    """Per query id: ``aligned`` when the recorded query inputs have the same stable identity in both runs."""

    def identities(queries: Sequence[Mapping[str, Any]]) -> dict[str, str]:
        return {str(q["query_id"]): query_input_identity({"query_id": q["query_id"], "text": q.get("query_text") or ""}) for q in queries}

    baseline = identities(await store.get_run_queries(baseline_run_id))
    candidate = identities(await store.get_run_queries(candidate_run_id))
    alignment: dict[str, Alignment] = {}
    for query_id in baseline.keys() | candidate.keys():
        if query_id not in baseline:
            alignment[query_id] = "missing_in_baseline"
        elif query_id not in candidate:
            alignment[query_id] = "missing_in_candidate"
        else:
            alignment[query_id] = "aligned" if baseline[query_id] == candidate[query_id] else "query_unaligned"
    return alignment


async def _selected_trace(store: Any, resolved: ResolvedScope, request: InvestigationRequest) -> RetrievalTrace | None:
    traces = await _list_traces(store, TraceQuery(run_id=resolved.run_id, pipeline_id=resolved.pipeline_id, query_id=request.query_id))
    return next((trace for trace in traces if trace.trace_id == request.trace_id), traces[0] if traces else None)


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        (offset,) = decode_cursor(cursor, 1)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("malformed pagination cursor")
    except ValueError as error:
        raise InvestigationError(400, "invalid_cursor", str(error))
    return offset


async def compare_investigations(store: Any, request: InvestigationRequest) -> dict:
    """Journey rows of the candidate (``run_id``) diffed against the baseline (``comparison_run_id``).

    Both scopes resolve under the candidate's ``EvaluationSpec``; manifests are checked with
    ``assess_evidence`` and per-query alignment comes from the stored query inputs. The diff is
    computed in memory and paged with an offset cursor (base64 JSON ``[offset]``), so a page is only
    stable while both projections stay unchanged. Never writes.
    """
    if not request.comparison_run_id:
        raise InvestigationError(400, "comparison_run_required", "against (the baseline run id) is required")
    from retrieval_observatory.release.assessment import assess_evidence  # release imports evidence; keep the cycle lazy

    candidate = await resolve_scope(store, request)
    baseline_request = replace(request, run_id=request.comparison_run_id, pipeline_id=request.comparison_pipeline_id or candidate.pipeline_id, k=candidate.spec.k)
    baseline = await resolve_scope(store, baseline_request)
    findings = [*candidate.findings, *(finding for finding in baseline.findings if finding not in candidate.findings)]

    assessment = assess_evidence(None, baseline.manifest, candidate.manifest)
    evidence_findings = [*assessment.readiness["aggregate_or_slice_evaluation"].findings, *assessment.readiness["promotion"].findings]
    corpus_changed = any(finding.code == "corpus_identity_mismatch" for finding in evidence_findings)
    hashes = [(manifest.get("dataset") or {}).get("query_input_hash") for manifest in (baseline.manifest, candidate.manifest)]
    unique: dict[str, Any] = {}
    for finding in evidence_findings:  # the promotion scope repeats the invariant findings under its own scope
        unique.setdefault(finding.code, finding)
    compatibility = {
        "provenance": assessment.provenance.model_dump(mode="json"),
        "findings": [finding.model_dump(mode="json") for finding in unique.values()],
        "corpus_changed": corpus_changed,
        "query_inputs_identical": None if None in hashes else hashes[0] == hashes[1],
    }

    baseline_rows, baseline_state, baseline_findings = await _comparison_rows(store, baseline, baseline_request)
    candidate_rows, candidate_state, candidate_findings = await _comparison_rows(store, candidate, request)
    if request.query_id and not baseline_rows and not candidate_rows:
        raise InvestigationError(404, "query_not_found", f"no rows for query {request.query_id!r} in run {candidate.run_id!r} or run {baseline.run_id!r}")
    alignment = await _query_alignment(store, baseline.run_id, candidate.run_id)
    diff = diff_journeys(baseline_rows, candidate_rows, query_alignment=alignment, corpus_changed=corpus_changed)

    stage_alignment = None
    if request.query_id:
        traces = (await _selected_trace(store, baseline, baseline_request), await _selected_trace(store, candidate, request))
        if all(traces):
            stage_alignment = align_stages(_stages(traces[0]), _stages(traces[1])).to_dict()

    findings.extend(baseline_findings)
    findings.extend(finding for finding in candidate_findings if finding not in findings)
    if corpus_changed:
        findings.append(_finding("unsupported_corpus_change", "corpus identity differs between the runs; entities are not matched across them", "compare final outputs per run; matched release claims are blocked"))
    if compatibility["query_inputs_identical"] is False or any(state != "aligned" for state in alignment.values()):
        findings.append(_finding("comparison_partial", "query inputs differ between the runs; unaligned queries carry no change classification", "compare aligned queries only, or rerun both runs on one query set"))

    offset = _offset(request.cursor)
    page = diff[offset : offset + request.limit]
    next_cursor = encode_cursor([offset + request.limit]) if offset + request.limit < len(diff) else None
    rows = [row.to_dict() for row in page]
    summary = summarize_journey_diff(diff)
    states = {baseline_state, candidate_state}
    projection = "unavailable" if "unavailable" in states else "partial" if "partial" in states else "ready"
    envelope = _envelope(candidate, request, projection=projection, rows=rows, total=len(diff), next_cursor=next_cursor, run_payload=None, summary=summary, stages=None, findings=findings)
    limited = sum(row["capture_limited"] for row in rows)
    envelope["capabilities"]["capture"] = {"complete_rows": len(rows) - limited, "partial_rows": limited}
    envelope["comparison"] = {
        "baseline_run_id": baseline.run_id,
        "candidate_run_id": candidate.run_id,
        "compatibility": compatibility,
        "stage_alignment": stage_alignment,
        "summary": summary,
    }
    return envelope
