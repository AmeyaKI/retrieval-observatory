"""Dependency-free normalization for already-exported OTel retrieval attributes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from retrieval_observatory.tracing.model import (
    CaptureMetadata,
    Candidate,
    OperatorSpan,
    RetrievalTrace,
)

_DERIVED_DECISIONS = {"derived", "expanded", "fused", "transformed"}


def _decoded(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _candidate(value: Mapping[str, Any]) -> tuple[Candidate | None, bool]:
    value = {key: _decoded(item) for key, item in value.items()}
    explicit_identity = bool(value.get("candidate_id") and value.get("logical_chunk_id"))
    doc_id = value.get("doc_id") or value.get("candidate_id")
    if doc_id is None or value.get("score") is None or value.get("rank") is None:
        return None, False
    parents = tuple(value.get("parent_candidate_ids") or ())
    decision = value.get("decision_reason") or value.get("drop_reason")
    missing_derived_parents = decision in _DERIVED_DECISIONS and not parents
    decision_evidence = value.get("decision_evidence")
    if decision_evidence is None:
        decision_evidence = "partial" if missing_derived_parents else ("recorded" if decision else "unavailable")
    if missing_derived_parents and decision_evidence == "recorded":
        decision_evidence = "partial"
    candidate = Candidate(
        doc_id=str(doc_id),
        score=float(value["score"]),
        rank=int(value["rank"]),
        input_rank=int(value["input_rank"]) if value.get("input_rank") is not None else None,
        output_rank=int(value["output_rank"]) if value.get("output_rank") is not None else None,
        candidate_id=str(value["candidate_id"]) if value.get("candidate_id") else str(doc_id),
        logical_chunk_id=(
            str(value["logical_chunk_id"]) if value.get("logical_chunk_id") else str(doc_id)
        ),
        document_id=str(value["document_id"]) if value.get("document_id") else None,
        document_revision=(
            str(value["document_revision"]) if value.get("document_revision") else None
        ),
        content_hash=str(value["content_hash"]) if value.get("content_hash") else None,
        parent_candidate_ids=parents,
        identity_evidence=value.get("identity_evidence", "recorded" if explicit_identity else "partial"),
        decision_reason=str(decision) if decision is not None else None,
        decision_evidence=decision_evidence,
        metadata=dict(value.get("metadata") or {}),
    )
    return candidate, explicit_identity and not missing_derived_parents


def _candidates(value: Any) -> tuple[tuple[Candidate, ...], bool]:
    decoded = _decoded(value) or ()
    items = []
    complete = True
    for raw in decoded:
        if not isinstance(raw, Mapping):
            complete = False
            continue
        candidate, item_complete = _candidate(raw)
        complete = complete and item_complete
        if candidate is not None:
            items.append(candidate)
    return tuple(items), complete


def normalize_otel_retrieval_trace(span: Mapping[str, Any]) -> RetrievalTrace:
    """Map explicit OTel/OpenInference-like attributes into one RetObs retrieval trace.

    The mapper has no OTel SDK dependency. Missing identity, parentage, exits, or
    topology stays partial; transition edges are never synthesized.
    """
    attributes = dict(span.get("attributes") or {})
    attributes = {key: _decoded(value) for key, value in attributes.items()}
    op_id = attributes.get("retobs.operator.id")
    op_type = attributes.get("retobs.operator.type")
    if not op_id or not op_type:
        raise ValueError("retobs.operator.id and retobs.operator.type are required")

    requested_parents = tuple(attributes.get("retobs.operator.parent_ids") or ())
    # A standalone exported span cannot prove that its parents were captured.
    parent_ids: tuple[str, ...] = ()
    complete = bool(
        span.get("trace_id")
        and attributes.get("retobs.query_id")
        and attributes.get("retobs.pipeline_id")
        and not requested_parents
        and op_type == "SOURCE"
    )
    raw_inputs = attributes.get("retobs.candidates.inputs") or {}
    if raw_inputs:
        complete = False

    outputs_present = "retobs.candidates.outputs" in attributes
    outputs, outputs_complete = _candidates(attributes.get("retobs.candidates.outputs"))
    complete = complete and outputs_present and outputs_complete
    output_ids = {candidate.candidate_id for candidate in outputs}
    for raw_group in raw_inputs.values() if isinstance(raw_inputs, Mapping) else ():
        candidates, group_complete = _candidates(raw_group)
        complete = complete and group_complete
        for candidate in candidates:
            if candidate.candidate_id not in output_ids and candidate.decision_evidence != "recorded":
                complete = False

    operator = OperatorSpan(
        op_id=str(op_id),
        op_type=str(op_type),
        op_name=str(span.get("name") or op_id),
        parent_ids=parent_ids,
        status=attributes.get("retobs.operator.status", "FIRED"),
        latency_ms=float(attributes.get("retobs.operator.latency_ms", 0.0)),
        outputs=outputs,
    )
    timestamp = span.get("timestamp") or span.get("start_time")
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now(timezone.utc)
    return RetrievalTrace(
        trace_id=str(span.get("trace_id") or ""),
        service_id=str(attributes.get("service.name") or attributes.get("retobs.service_id") or ""),
        run_id=attributes.get("retobs.run_id"),
        query_id=str(attributes.get("retobs.query_id") or ""),
        query_text=str(attributes.get("retobs.query_text") or ""),
        pipeline_id=str(attributes.get("retobs.pipeline_id") or ""),
        spans=(operator,),
        final_op_ids=tuple(attributes.get("retobs.trace.final_op_ids") or ()),
        timestamp=timestamp,
        capture=CaptureMetadata(
            instrumentation_version=str(attributes.get("retobs.instrumentation.version") or "otel-adapter-1"),
            sample_rate=float(attributes.get("retobs.capture.sample_rate", 1.0)),
            sampled=bool(attributes.get("retobs.capture.sampled", True)),
            lineage_evidence="recorded" if complete else "partial",
        ),
        metadata={"telemetry_source": "otel"},
        schema_version=int(attributes.get("retobs.trace.schema_version", 1)),
    )
