from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from retrieval_observatory.config.schema import ReleaseIdentityConfig
from retrieval_observatory.store.base import InstrumentationHealth
from retrieval_observatory.tracing.model import Candidate, RetrievalTrace


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReleaseIdentity(ReleaseIdentityConfig):
    model_config = ConfigDict(extra="forbid", strict=True)


class RunWindow(_EvidenceModel):
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LineageCoverage(_EvidenceModel):
    trace_coverage: float | None = Field(default=None, ge=0, le=1)
    identity_continuity_coverage: float | None = Field(default=None, ge=0, le=1)
    document_identity_coverage: float | None = Field(default=None, ge=0, le=1)
    input_output_coverage: float | None = Field(default=None, ge=0, le=1)
    recorded_exit_reason_coverage: float | None = Field(default=None, ge=0, le=1)
    topology_edge_coverage: float | None = Field(default=None, ge=0, le=1)
    qrel_to_chunk_mapping_coverage: float | None = Field(default=None, ge=0, le=1)
    legacy_inferred_count: int = Field(ge=0)
    partial_trace_count: int = Field(ge=0)


class TopologyOperator(_EvidenceModel):
    op_id: str
    op_type: str
    parent_ids: list[str]


class TopologyDescriptor(_EvidenceModel):
    topology_hash: str
    operators: list[TopologyOperator]
    lineage_schema_versions: list[int]


class TelemetryEvidence(_EvidenceModel):
    service_id: str
    accepted: int = Field(ge=0)
    exported: int = Field(ge=0)
    dropped: int = Field(ge=0)
    serialization_failures: int = Field(ge=0)
    retries: int = Field(ge=0)
    permanent_failures: int = Field(ge=0)
    sample_rate: float = Field(ge=0, le=1)
    observed_at: datetime


class EvidenceProfile(_EvidenceModel):
    release_identity: ReleaseIdentity
    run_window: RunWindow
    lineage: LineageCoverage
    topologies: list[TopologyDescriptor]
    telemetry: TelemetryEvidence | None = None

    @classmethod
    def from_run(
        cls,
        manifest: Mapping[str, Any],
        traces: Sequence[RetrievalTrace],
        health: InstrumentationHealth | Mapping[str, Any] | None,
    ) -> EvidenceProfile:
        run_window = _run_window(manifest)
        scoped_traces = [trace for trace in traces if _in_window(trace.timestamp, run_window)]
        return cls(
            release_identity=ReleaseIdentity.model_validate(manifest.get("release_identity", {})),
            run_window=run_window,
            lineage=_lineage_coverage(manifest, scoped_traces),
            topologies=_topology_descriptors(scoped_traces),
            telemetry=_telemetry_in_window(health, run_window),
        )


def _run_window(manifest: Mapping[str, Any]) -> RunWindow:
    value = manifest.get("run_window") or {}
    return RunWindow(
        started_at=_datetime(value.get("started_at") or manifest.get("started_at")),
        finished_at=_datetime(value.get("finished_at") or manifest.get("finished_at")),
    )


def _datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _in_window(timestamp: datetime, window: RunWindow) -> bool:
    if window.started_at is not None and timestamp < window.started_at:
        return False
    if window.finished_at is not None and timestamp > window.finished_at:
        return False
    return True


def _candidate_sets(trace: RetrievalTrace) -> list[tuple[Candidate, ...]]:
    return [
        candidates
        for span in trace.spans
        for candidates in (*span.input_groups.values(), span.outputs)
    ]


def _coverage(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _lineage_coverage(manifest: Mapping[str, Any], traces: Sequence[RetrievalTrace]) -> LineageCoverage:
    candidates = [candidate for trace in traces for group in _candidate_sets(trace) for candidate in group]
    exit_candidates = [
        candidate
        for trace in traces
        for span in trace.spans
        for group in span.input_groups.values()
        for candidate in group
        if candidate.output_rank is None
    ]
    spans = [span for trace in traces for span in trace.spans]
    complete_spans = sum(
        span.op_type == "SOURCE" or all(parent_id in span.input_groups for parent_id in span.parent_ids)
        for span in spans
    )
    declared_edges = sum(len(span.parent_ids) for span in spans)
    observed_edges = sum(
        parent_id in span.input_groups
        for span in spans
        for parent_id in span.parent_ids
    )
    legacy_inferred_count = sum(
        candidate.identity_evidence == "legacy_inferred" or candidate.decision_evidence == "legacy_inferred"
        for candidate in candidates
    )
    partial_trace_count = sum(_trace_is_partial(trace) for trace in traces)
    expected_traces = _expected_trace_count(manifest)
    return LineageCoverage(
        trace_coverage=(
            _coverage(min(len(traces), expected_traces), expected_traces)
            if expected_traces is not None
            else None
        ),
        identity_continuity_coverage=_coverage(
            sum(candidate.identity_evidence == "recorded" for candidate in candidates),
            len(candidates),
        ),
        document_identity_coverage=_coverage(
            sum(
                candidate.identity_evidence == "recorded"
                and candidate.logical_chunk_id is not None
                and bool(candidate.document_revision or candidate.content_hash)
                for candidate in candidates
            ),
            len(candidates),
        ),
        input_output_coverage=_coverage(complete_spans, len(spans)),
        recorded_exit_reason_coverage=_coverage(
            sum(candidate.decision_evidence == "recorded" for candidate in exit_candidates),
            len(exit_candidates),
        ),
        topology_edge_coverage=_coverage(observed_edges, declared_edges),
        qrel_to_chunk_mapping_coverage=None,
        legacy_inferred_count=legacy_inferred_count,
        partial_trace_count=partial_trace_count,
    )


def _expected_trace_count(manifest: Mapping[str, Any]) -> int | None:
    attempted = (manifest.get("counts") or {}).get("attempted")
    normalized = manifest.get("normalized_config") or {}
    pipeline_count = len(normalized.get("pipelines") or ()) + len(normalized.get("graphs") or ())
    if attempted is None or pipeline_count == 0:
        return None
    return int(attempted) * pipeline_count


def _trace_is_partial(trace: RetrievalTrace) -> bool:
    candidates = [candidate for group in _candidate_sets(trace) for candidate in group]
    missing_parent_group = any(
        parent_id not in span.input_groups
        for span in trace.spans
        for parent_id in span.parent_ids
    )
    return bool(
        trace.capture.candidates_truncated
        or trace.capture.omitted_field_count
        or missing_parent_group
        or any(candidate.identity_evidence in {"partial", "unavailable"} for candidate in candidates)
    )


def _topology_descriptors(traces: Sequence[RetrievalTrace]) -> list[TopologyDescriptor]:
    grouped: dict[str, list[RetrievalTrace]] = {}
    for trace in traces:
        grouped.setdefault(trace.topology_hash(), []).append(trace)
    return [
        TopologyDescriptor(
            topology_hash=topology_hash,
            operators=[
                TopologyOperator(op_id=span.op_id, op_type=span.op_type, parent_ids=sorted(span.parent_ids))
                for span in sorted(items[0].spans, key=lambda item: item.op_id)
            ],
            lineage_schema_versions=sorted({trace.lineage_schema_version for trace in items}),
        )
        for topology_hash, items in sorted(grouped.items())
    ]


def _telemetry_in_window(
    health: InstrumentationHealth | Mapping[str, Any] | None,
    window: RunWindow,
) -> TelemetryEvidence | None:
    if health is None:
        return None
    value = health if isinstance(health, Mapping) else health.__dict__
    observed_at = _datetime(value.get("observed_at"))
    if observed_at is None or not _in_window(observed_at, window):
        return None
    return TelemetryEvidence(
        service_id=str(value["service_id"]),
        accepted=int(value.get("accepted", 0)),
        exported=int(value.get("exported", 0)),
        dropped=int(value.get("dropped", 0)),
        serialization_failures=int(value.get("serialization_failures", 0)),
        retries=int(value.get("retries", 0)),
        permanent_failures=int(value.get("permanent_failures", 0)),
        sample_rate=float(value.get("sample_rate", 1.0)),
        observed_at=observed_at,
    )
