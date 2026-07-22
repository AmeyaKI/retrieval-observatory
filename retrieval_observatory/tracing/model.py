from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Literal, Mapping, Sequence

from retrieval_observatory.tracing.lineage_contract import (
    LineageEvidence,
    validate_candidate_parentage,
    validate_lineage_evidence,
    validate_unique_candidate_ids,
)

OperatorType = Literal["SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE", "TRANSFORM", "GENERATE"]
OperatorStatus = Literal["FIRED", "SKIPPED_BY_GATE", "ERROR", "TIMEOUT"]
ReplayPolicy = Literal["EXACT", "OBSERVED_ABLATION", "NOT_REPLAYABLE"]


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


@dataclass(frozen=True)
class OperatorSpan:
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

    def __post_init__(self) -> None:
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
        cls, op_id: str, op_name: str, outputs: Sequence[Candidate], parent_ids: tuple[str, ...] = ()
    ) -> "OperatorSpan":
        return cls(op_id, "SOURCE", op_name, parent_ids, "FIRED", 0.0, outputs=tuple(outputs))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("inputs", None)
        payload.pop("final_op_id", None)
        payload["parent_ids"] = list(self.parent_ids)
        payload["input_groups"] = {key: [asdict(item) for item in value] for key, value in self.input_groups.items()}
        payload["outputs"] = [asdict(item) for item in self.outputs]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorSpan":
        return cls(
            op_id=str(value["op_id"]),
            op_type=value["op_type"],
            op_name=str(value.get("op_name", value["op_id"])),
            parent_ids=tuple(value.get("parent_ids", ())),
            status=value.get("status", "FIRED"),
            latency_ms=float(value.get("latency_ms", 0.0)),
            input_groups={
                key: tuple(Candidate.from_dict(item) for item in items)
                for key, items in value.get("input_groups", {}).items()
            },
            outputs=tuple(Candidate.from_dict(item) for item in value.get("outputs", ())),
            deterministic=bool(value.get("deterministic", False)),
            replay_policy=value.get("replay_policy", "NOT_REPLAYABLE"),
            params=dict(value.get("params", {})),
            gate_values=dict(value.get("gate_values", {})),
            input_variant=str(value.get("input_variant", "raw")),
            error=value.get("error"),
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
    omitted_field_count: int = 0
    lineage_evidence: LineageEvidence = "recorded"

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
        }

    @property
    def total_latency_ms(self) -> float:
        return self.timing.wall_clock_ms if self.timing is not None else 0.0

    def topology_hash(self) -> str:
        """Stable graph signature used by both storage backends."""
        topology = [
            (span.op_id, span.op_type, tuple(span.parent_ids), span.status)
            for span in sorted(self.spans, key=lambda item: item.op_id)
        ]
        return sha256(json.dumps(topology, separators=(",", ":")).encode("utf-8")).hexdigest()

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
            final_op_ids=tuple(value.get("final_op_ids", ())),
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
        )
