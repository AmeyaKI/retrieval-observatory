from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Candidate":
        return cls(
            **{
                **value,
                "origin_op_ids": tuple(value.get("origin_op_ids", ())),
                "score_components": dict(value.get("score_components", {})),
                "metadata": dict(value.get("metadata", {})),
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

    def __post_init__(self) -> None:
        groups = {key: tuple(value) for key, value in self.input_groups.items()}
        if set(groups) - set(self.parent_ids):
            raise ValueError("input group keys must be declared parent IDs")
        object.__setattr__(self, "parent_ids", tuple(self.parent_ids))
        object.__setattr__(self, "input_groups", groups)
        object.__setattr__(self, "outputs", tuple(self.outputs))

    @property
    def inputs(self) -> tuple[Candidate, ...]:
        return tuple(candidate for parent in self.parent_ids for candidate in self.input_groups.get(parent, ()))

    @classmethod
    def source(
        cls, op_id: str, op_name: str, outputs: Sequence[Candidate], parent_ids: tuple[str, ...] = ()
    ) -> "OperatorSpan":
        return cls(op_id, "SOURCE", op_name, parent_ids, "FIRED", 0.0, outputs=tuple(outputs))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
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
            cache[op_id] = max((duration(parent) for parent in span.parent_ids), default=0.0) + max(
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

    def __post_init__(self) -> None:
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")


@dataclass(frozen=True)
class RetrievalTrace:
    trace_id: str
    service_id: str
    run_id: str | None
    query_id: str
    query_text: str
    pipeline_id: str
    spans: Sequence[OperatorSpan]
    final_op_ids: tuple[str, ...]
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
        if not set(self.final_op_ids) <= known:
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
        object.__setattr__(self, "final_op_ids", tuple(self.final_op_ids))
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
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetrievalTrace":
        return cls(
            trace_id=str(value["trace_id"]),
            service_id=str(value["service_id"]),
            run_id=value.get("run_id"),
            query_id=str(value["query_id"]),
            query_text=str(value.get("query_text", "")),
            pipeline_id=str(value["pipeline_id"]),
            spans=tuple(OperatorSpan.from_dict(item) for item in value.get("spans", ())),
            final_op_ids=tuple(value.get("final_op_ids", ())),
            timestamp=datetime.fromisoformat(str(value["timestamp"])),
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
        )
