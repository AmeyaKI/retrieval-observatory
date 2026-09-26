from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Literal, Mapping, Sequence

from retrieval_observatory.tracing.lineage_contract import (
    LineageEvidence,
    ParentLinkage,
    validate_candidate_parentage,
    validate_lineage_evidence,
    validate_parent_linkage,
    validate_unique_candidate_ids,
)

OperatorType = Literal["SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE", "TRANSFORM", "GENERATE"]
OperatorStatus = Literal["FIRED", "SKIPPED_BY_GATE", "ERROR", "TIMEOUT"]
ReplayPolicy = Literal["EXACT", "OBSERVED_ABLATION", "NOT_REPLAYABLE"]
# How an operator's boundary was captured: its actual bound arguments / returned object
# ("recorded"), lanes matched to parents by position ("positional"), reconstructed from parent
# spans ("inferred"), not captured at all ("unavailable"), or a source whose input is the query.
InputCapture = Literal["recorded", "positional", "inferred", "unavailable", "not_applicable"]
OutputCapture = Literal["recorded", "truncated", "unavailable"]
_INPUT_CAPTURE_VALUES = {"recorded", "positional", "inferred", "unavailable", "not_applicable"}
_OUTPUT_CAPTURE_VALUES = {"recorded", "truncated", "unavailable"}


@dataclass
class Candidate:
    doc_id: str
    score: float
    rank: int
    input_rank: int | None = None
    output_rank: int | None = None
    origin_op_ids: tuple[str, ...] = ()
    score_components: Mapping[str, float] = field(default_factory=dict)
    add_reason: str = "retrieved"
    drop_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    candidate_id: str | None = None
    logical_chunk_id: str | None = None
    document_id: str | None = None
    document_revision: str | None = None
    content_hash: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    parent_candidate_ids: tuple[str, ...] = ()
    identity_evidence: LineageEvidence = "recorded"
    decision_reason: str | None = None
    decision_evidence: LineageEvidence = "unavailable"
    score_type: str | None = None
    score_model: str | None = None

    def __post_init__(self) -> None:
        self.candidate_id = self.candidate_id or self.doc_id
        self.logical_chunk_id = self.logical_chunk_id or self.doc_id
        self.origin_op_ids = tuple(self.origin_op_ids)
        self.score_components = dict(self.score_components)
        self.metadata = dict(self.metadata)
        self.parent_candidate_ids = tuple(self.parent_candidate_ids)
        if not self.candidate_id or any(not parent_id for parent_id in self.parent_candidate_ids):
            raise ValueError("candidate and parent candidate IDs must be non-empty")
        if len(self.parent_candidate_ids) != len(set(self.parent_candidate_ids)):
            raise ValueError("parent candidate IDs must be unique")
        validate_lineage_evidence(self.identity_evidence, field_name="identity_evidence")
        validate_lineage_evidence(self.decision_evidence, field_name="decision_evidence")
        validate_candidate_parentage(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Candidate":
        has_recorded_identity = bool(value.get("candidate_id")) and bool(value.get("logical_chunk_id"))
        return cls(
            **{
                **value,
                "origin_op_ids": tuple(value.get("origin_op_ids", ())),
                "score_components": dict(value.get("score_components", {})),
                "metadata": dict(value.get("metadata", {})),
                "candidate_id": value.get("candidate_id") or value["doc_id"],
                "logical_chunk_id": value.get("logical_chunk_id") or value["doc_id"],
                "parent_candidate_ids": tuple(value.get("parent_candidate_ids", ())),
                "identity_evidence": (
                    value.get("identity_evidence", "recorded") if has_recorded_identity else "legacy_inferred"
                ),
                "decision_evidence": value.get("decision_evidence") or (
                    "legacy_inferred" if value.get("drop_reason") else "unavailable"
                ),
            }
        )


def next_node_id(existing_op_ids: Iterable[str], operator_id: str) -> str:
    """The node key for a new invocation of ``operator_id``: the operator id itself, else ``id#n``."""
    existing = set(existing_op_ids)
    if operator_id not in existing:
        return operator_id
    n = 2
    while f"{operator_id}#{n}" in existing:
        n += 1
    return f"{operator_id}#{n}"


def latest_span_of(spans: Iterable["OperatorSpan"], operator_id: str) -> "OperatorSpan | None":
    """The latest invocation of an operator, falling back to node-key equality for old traces."""
    spans = list(spans)
    for span in reversed(spans):
        if span.operator_id == operator_id:
            return span
    for span in reversed(spans):
        if span.op_id == operator_id:
            return span
    return None


@dataclass(frozen=True)
class OperatorSpan:
    # ``op_id`` is the per-trace NODE key (unique within a trace); ``operator_id`` is the stable
    # operator identity shared by repeated invocations (``rerank``, ``rerank#2``).
    op_id: str
    op_type: OperatorType
    op_name: str
    parent_ids: tuple[str, ...]
    status: OperatorStatus
    latency_ms: float
    input_groups: Mapping[str, tuple[Candidate, ...]] = field(default_factory=dict)
    outputs: tuple[Candidate, ...] = ()
    deterministic: bool = False
    replay_policy: ReplayPolicy = "NOT_REPLAYABLE"
    params: Mapping[str, Any] = field(default_factory=dict)
    gate_values: Mapping[str, Any] = field(default_factory=dict)
    input_variant: str = "raw"
    error: str | None = None
    inputs: tuple[Candidate, ...] = ()
    branch_id: str | None = None
    invocation_id: str | None = None
    input_capture: InputCapture = "recorded"
    output_capture: OutputCapture = "recorded"
    source_ref: str | None = None
    operator_id: str | None = None
    # ``invocation_id`` of the span behind each ``parent_ids`` entry, in that order; empty when unknown.
    parent_invocation_ids: tuple[str, ...] = ()
    parent_linkage: ParentLinkage = "declared"

    def __post_init__(self) -> None:
        if self.input_capture not in _INPUT_CAPTURE_VALUES:
            raise ValueError(f"input_capture must be one of {sorted(_INPUT_CAPTURE_VALUES)}")
        if self.output_capture not in _OUTPUT_CAPTURE_VALUES:
            raise ValueError(f"output_capture must be one of {sorted(_OUTPUT_CAPTURE_VALUES)}")
        validate_parent_linkage(self.parent_linkage)
        object.__setattr__(self, "operator_id", self.operator_id or self.op_id)
        object.__setattr__(self, "parent_invocation_ids", tuple(self.parent_invocation_ids))
        groups = {key: tuple(value) for key, value in self.input_groups.items()}
        inputs = tuple(self.inputs)
        if set(groups) - set(self.parent_ids):
            raise ValueError("input group keys must be declared parent IDs")
        if inputs and not groups and self.parent_ids:
            groups = {self.parent_ids[0]: inputs}
        object.__setattr__(self, "parent_ids", tuple(self.parent_ids))
        object.__setattr__(self, "input_groups", groups)
        object.__setattr__(self, "inputs", tuple(candidate for parent in self.parent_ids for candidate in groups.get(parent, ())))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        for candidates in (*groups.values(), self.outputs):
            validate_unique_candidate_ids(candidates)

    @classmethod
    def source(
        cls,
        op_id: str,
        op_name: str,
        outputs: Sequence[Candidate],
        parent_ids: tuple[str, ...] = (),
        branch_id: str | None = None,
    ) -> "OperatorSpan":
        return cls(
            op_id,
            "SOURCE",
            op_name,
            parent_ids,
            "FIRED",
            0.0,
            outputs=tuple(outputs),
            branch_id=branch_id,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("inputs", None)
        payload.pop("final_op_id", None)
        payload["parent_ids"] = list(self.parent_ids)
        payload["parent_invocation_ids"] = list(self.parent_invocation_ids)
        payload["input_groups"] = {key: [asdict(item) for item in value] for key, value in self.input_groups.items()}
        payload["outputs"] = [asdict(item) for item in self.outputs]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorSpan":
        parent_ids = tuple(value.get("parent_ids", ()))
        status = value.get("status", "FIRED")
        input_groups = {
            key: tuple(Candidate.from_dict(item) for item in items)
            for key, items in value.get("input_groups", {}).items()
        }
        # Payloads written before boundary capture existed reconstructed inputs from parent spans.
        return cls(
            op_id=str(value["op_id"]),
            op_type=value["op_type"],
            op_name=str(value.get("op_name", value["op_id"])),
            parent_ids=parent_ids,
            status=status,
            latency_ms=float(value.get("latency_ms", 0.0)),
            input_groups=input_groups,
            outputs=tuple(Candidate.from_dict(item) for item in value.get("outputs", ())),
            deterministic=bool(value.get("deterministic", False)),
            replay_policy=value.get("replay_policy", "NOT_REPLAYABLE"),
            params=dict(value.get("params", {})),
            gate_values=dict(value.get("gate_values", {})),
            input_variant=str(value.get("input_variant", "raw")),
            error=value.get("error"),
            branch_id=value.get("branch_id"),
            invocation_id=value.get("invocation_id"),
            input_capture=value.get("input_capture")
            or ("not_applicable" if not parent_ids else "inferred" if input_groups else "unavailable"),
            output_capture=value.get("output_capture") or ("recorded" if status == "FIRED" else "unavailable"),
            source_ref=value.get("source_ref"),
            operator_id=value.get("operator_id") or str(value["op_id"]),
            parent_invocation_ids=tuple(value.get("parent_invocation_ids", ())),
            parent_linkage=value.get("parent_linkage") or ("declared" if parent_ids else "recorded"),
        )


def critical_path_latency_ms(spans: Sequence[OperatorSpan]) -> float:
    by_id = {span.op_id: span for span in spans}
    cache: dict[str, float] = {}

    def duration(op_id: str) -> float:
        if op_id not in cache:
            span = by_id[op_id]
            cache[op_id] = max((duration(parent) for parent in span.parent_ids if parent in by_id), default=0.0) + max(
                0.0, span.latency_ms
            )
        return cache[op_id]

    return max((duration(op_id) for op_id in by_id), default=0.0)


@dataclass(frozen=True)
class TraceTiming:
    wall_clock_ms: float
    critical_path_ms: float
    operator_sum_ms: float
    semantics_version: int = 1

    @classmethod
    def from_spans(cls, spans: Sequence[OperatorSpan]) -> "TraceTiming":
        critical = critical_path_latency_ms(spans)
        return cls(critical, critical, sum(max(0.0, span.latency_ms) for span in spans))


@dataclass(frozen=True)
class CaptureMetadata:
    instrumentation_version: str = "1"
    sample_rate: float = 1.0
    sampled: bool = True
    candidates_truncated: bool = False
    redacted_field_count: int = 0
    # Structural omissions only (dropped collection items, depth cut-offs, popped
    # candidate metadata/text). These make lineage partial.
    omitted_field_count: int = 0
    # Strings clipped to `PayloadLimits.max_string_chars`. Clipping a chunk's text
    # loses no candidate, decision, or edge, so it never makes lineage partial.
    truncated_string_count: int = 0
    lineage_evidence: LineageEvidence = "recorded"
    # Spans whose input or output capture is neither "recorded" nor "not_applicable".
    incomplete_boundary_count: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")
        validate_lineage_evidence(self.lineage_evidence, field_name="lineage_evidence")


@dataclass
class RetrievalTrace:
    trace_id: str
    service_id: str
    run_id: str | None
    query_id: str
    query_text: str
    pipeline_id: str
    spans: Sequence[OperatorSpan]
    final_op_ids: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dataset_id: str | None = None
    corpus_version: str | None = None
    index_version: str | None = None
    request_id: str | None = None
    status: Literal["OK", "TIMEOUT", "ERROR"] = "OK"
    timing: TraceTiming | None = None
    capture: CaptureMetadata = field(default_factory=CaptureMetadata)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error_traceback: str | None = None
    schema_version: int = 1
    lineage_schema_version: int = 2
    final_op_id: str | None = None
    # Boundary-capture failures recorded by ``@observe``; each is
    # {"op_id", "invocation_id", "phase", "code", "detail"}. Never raised into the application.
    capture_failures: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        spans = tuple(self.spans)
        ids = [span.op_id for span in spans]
        if len(ids) != len(set(ids)):
            raise ValueError("operator IDs must be unique within a trace")
        known = set(ids)
        for span in spans:
            for parent in span.parent_ids:
                if parent not in known:
                    raise ValueError(f"unknown parent {parent}")
        final_op_ids = tuple(self.final_op_ids) or ((self.final_op_id,) if self.final_op_id else ())
        if not set(final_op_ids) <= known:
            raise ValueError("final operator IDs must exist in spans")
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {span.op_id: span for span in spans}

        def visit(op_id: str) -> None:
            if op_id in visiting:
                raise ValueError("operator graph must be acyclic")
            if op_id in visited:
                return
            visiting.add(op_id)
            for parent in by_id[op_id].parent_ids:
                visit(parent)
            visiting.remove(op_id)
            visited.add(op_id)

        for op_id in ids:
            visit(op_id)
        for span in spans:
            for candidates in (*span.input_groups.values(), span.outputs):
                ranks = [candidate.rank for candidate in candidates]
                if any(rank < 1 for rank in ranks) or len(ranks) != len(set(ranks)):
                    raise ValueError("candidate ranks must be positive and unique within a group")
        object.__setattr__(self, "spans", spans)
        object.__setattr__(self, "final_op_ids", final_op_ids)
        object.__setattr__(self, "final_op_id", final_op_ids[0] if len(final_op_ids) == 1 else None)
        object.__setattr__(self, "capture_failures", tuple(dict(item) for item in self.capture_failures))
        if self.lineage_schema_version < 1:
            raise ValueError("lineage schema version must be positive")
        if self.timing is None:
            object.__setattr__(self, "timing", TraceTiming.from_spans(spans))

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "service_id": self.service_id,
            "run_id": self.run_id,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "pipeline_id": self.pipeline_id,
            "spans": [span.to_dict() for span in self.spans],
            "final_op_ids": list(self.final_op_ids),
            "timestamp": self.timestamp.isoformat(),
            "dataset_id": self.dataset_id,
            "corpus_version": self.corpus_version,
            "index_version": self.index_version,
            "request_id": self.request_id,
            "status": self.status,
            "timing": asdict(self.timing),
            "capture": asdict(self.capture),
            "metadata": dict(self.metadata),
            "error_traceback": self.error_traceback,
            "schema_version": self.schema_version,
            "lineage_schema_version": self.lineage_schema_version,
            "capture_failures": [dict(item) for item in self.capture_failures],
        }

    @property
    def total_latency_ms(self) -> float:
        return self.timing.wall_clock_ms if self.timing is not None else 0.0

    def topology_hash(self) -> str:
        """Stable graph signature used by both storage backends.

        Hashed by operator identity, so repeated invocations of one operator collapse into
        one node and the signature does not depend on how many times an operator ran."""
        operator_of = {span.op_id: span.operator_id for span in self.spans}
        topology = sorted(
            {
                (span.operator_id, span.op_type, tuple(sorted(operator_of[p] for p in span.parent_ids)), span.status)
                for span in self.spans
            }
        )
        return sha256(json.dumps(topology, separators=(",", ":")).encode("utf-8")).hexdigest()

    def invocations_of(self, operator_id: str) -> tuple[OperatorSpan, ...]:
        return tuple(span for span in self.spans if span.operator_id == operator_id)

    def with_identity(self, *, run_id: str | None, service_id: str) -> "RetrievalTrace":
        return RetrievalTrace(
            **{
                **self.to_dict(),
                "run_id": run_id,
                "service_id": service_id,
                "timestamp": self.timestamp,
                "spans": self.spans,
                "timing": self.timing,
                "capture": self.capture,
            }
        )

    def span(self, op_id: str) -> OperatorSpan:
        for span in self.spans:
            if span.op_id == op_id:
                return span
        raise KeyError(op_id)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetrievalTrace":
        return cls(
            trace_id=str(value["trace_id"]),
            service_id=str(value.get("service_id", "remote")),
            run_id=value.get("run_id"),
            query_id=str(value["query_id"]),
            query_text=str(value.get("query_text", "")),
            pipeline_id=str(value["pipeline_id"]),
            spans=tuple(OperatorSpan.from_dict(item) for item in value.get("spans", ())),
            final_op_ids=tuple(
                value.get("final_op_ids")
                or ((value["final_op_id"],) if value.get("final_op_id") else ())
            ),
            timestamp=datetime.fromisoformat(str(value["timestamp"])) if value.get("timestamp") else datetime.now(timezone.utc),
            dataset_id=value.get("dataset_id"),
            corpus_version=value.get("corpus_version"),
            index_version=value.get("index_version"),
            request_id=value.get("request_id"),
            status=value.get("status", "OK"),
            timing=TraceTiming(**value["timing"]) if value.get("timing") else None,
            capture=CaptureMetadata(**value.get("capture", {})),
            metadata=dict(value.get("metadata", {})),
            error_traceback=value.get("error_traceback"),
            schema_version=int(value.get("schema_version", 1)),
            lineage_schema_version=int(value.get("lineage_schema_version", 1)),
            capture_failures=tuple(dict(item) for item in value.get("capture_failures", ())),
        )
