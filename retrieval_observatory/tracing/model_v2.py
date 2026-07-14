from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

OperatorType = Literal["SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE", "TRANSFORM", "GENERATE"]
OperatorStatus = Literal["FIRED", "SKIPPED_BY_GATE", "ERROR", "TIMEOUT"]
ReplayPolicy = Literal["EXACT", "OBSERVED_ABLATION", "NOT_REPLAYABLE"]
AddReason = Literal["retrieved", "expanded", "fused", "transformed", "boosted"]
DropReason = Literal["filtered", "reranked_out", "gate_blocked", "deduped", "truncated", "unknown"]


@dataclass
class Candidate:
    doc_id: str
    score: float
    rank: int
    input_rank: int | None = None
    output_rank: int | None = None
    origin_op_ids: List[str] = field(default_factory=list)
    score_components: Dict[str, float] = field(default_factory=dict)
    add_reason: AddReason = "retrieved"
    drop_reason: DropReason | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OperatorSpan:
    op_id: str
    op_type: OperatorType
    op_name: str
    parent_ids: List[str]
    status: OperatorStatus
    deterministic: bool
    replay_policy: ReplayPolicy
    latency_ms: float
    inputs: List[Candidate] = field(default_factory=list)
    outputs: List[Candidate] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    gate_values: Dict[str, Any] = field(default_factory=dict)
    input_variant: str = "raw"
    error: str | None = None


@dataclass
class TraceTiming:
    """Unambiguous latency views for a trace.

    ``wall_clock_ms`` is user-observed elapsed time, ``critical_path_ms`` is the
    longest parent-to-child path, and ``operator_sum_ms`` is aggregate operator
    work. They are equal for a simple serial pipeline but intentionally differ
    for parallel DAGs.
    """

    wall_clock_ms: float
    critical_path_ms: float
    operator_sum_ms: float
    semantics_version: int = 1

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TraceTiming":
        return cls(
            wall_clock_ms=float(payload.get("wall_clock_ms", 0.0)),
            critical_path_ms=float(payload.get("critical_path_ms", 0.0)),
            operator_sum_ms=float(payload.get("operator_sum_ms", 0.0)),
            semantics_version=int(payload.get("semantics_version", 1)),
        )


def critical_path_latency_ms(spans: List[OperatorSpan]) -> float:
    """Return the longest observed parent path without inventing missing edges."""
    by_id = {span.op_id: span for span in spans}
    cache: Dict[str, float] = {}

    def duration(op_id: str, visiting: frozenset[str]) -> float:
        if op_id in cache:
            return cache[op_id]
        if op_id in visiting:
            return 0.0
        span = by_id[op_id]
        parents = [parent for parent in span.parent_ids if parent in by_id]
        parent_duration = max(
            (duration(parent, visiting | {op_id}) for parent in parents),
            default=0.0,
        )
        value = parent_duration + max(0.0, float(span.latency_ms))
        cache[op_id] = value
        return value

    return max((duration(op_id, frozenset()) for op_id in by_id), default=0.0)


@dataclass
class RetrievalTraceV2:
    trace_id: str
    run_id: str
    query_id: str
    query_text: str
    pipeline_id: str
    spans: List[OperatorSpan]
    total_latency_ms: float
    timing: TraceTiming | None = None
    status: Literal["OK", "TIMEOUT", "ERROR"] = "OK"
    trace_format_version: int = 2
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_traceback: str | None = None
    request_id: str | None = None
    final_op_id: str | None = None

    def __post_init__(self) -> None:
        if self.timing is None:
            operator_sum = sum(max(0.0, float(span.latency_ms)) for span in self.spans)
            critical_path = critical_path_latency_ms(self.spans)
            self.timing = TraceTiming(
                wall_clock_ms=float(self.total_latency_ms),
                critical_path_ms=critical_path or float(self.total_latency_ms),
                operator_sum_ms=operator_sum or float(self.total_latency_ms),
            )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RetrievalTraceV2":
        spans = []
        for s in payload.get("spans", []):
            inputs = [Candidate(**c) for c in s.get("inputs", [])]
            outputs = [Candidate(**c) for c in s.get("outputs", [])]
            spans.append(
                OperatorSpan(
                    op_id=s["op_id"],
                    op_type=s["op_type"],
                    op_name=s.get("op_name", s["op_id"]),
                    parent_ids=list(s.get("parent_ids", [])),
                    status=s.get("status", "FIRED"),
                    deterministic=bool(s.get("deterministic", False)),
                    replay_policy=s.get("replay_policy", "NOT_REPLAYABLE"),
                    latency_ms=float(s.get("latency_ms", 0.0)),
                    inputs=inputs,
                    outputs=outputs,
                    params=dict(s.get("params", {})),
                    gate_values=dict(s.get("gate_values", {})),
                    input_variant=str(s.get("input_variant", "raw")),
                    error=s.get("error"),
                )
            )
        ts = payload.get("timestamp")
        timestamp = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
        return cls(
            trace_id=payload["trace_id"],
            run_id=payload.get("run_id", ""),
            query_id=payload.get("query_id", ""),
            query_text=payload.get("query_text", ""),
            pipeline_id=payload.get("pipeline_id", ""),
            spans=spans,
            total_latency_ms=float(payload.get("total_latency_ms", 0.0)),
            timing=(
                TraceTiming.from_dict(payload["timing"])
                if isinstance(payload.get("timing"), dict)
                else None
            ),
            status=payload.get("status", "OK"),
            trace_format_version=int(payload.get("trace_format_version", 2)),
            timestamp=timestamp,
            metadata=dict(payload.get("metadata", {})),
            error_traceback=payload.get("error_traceback"),
            request_id=payload.get("request_id"),
            final_op_id=payload.get("final_op_id"),
        )
