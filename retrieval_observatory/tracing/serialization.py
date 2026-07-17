import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from retrieval_observatory.tracing.config import PayloadLimits
from retrieval_observatory.tracing.model import RetrievalTrace


@dataclass(frozen=True)
class NormalizationReport:
    redacted_fields: int = 0
    omitted_fields: int = 0
    omitted_candidates: int = 0


@dataclass(frozen=True)
class NormalizedTrace:
    payload: dict[str, Any]
    report: NormalizationReport
    failed: bool = False


@dataclass
class _MutableReport:
    redacted_fields: int = 0
    omitted_fields: int = 0
    omitted_candidates: int = 0

    def freeze(self) -> NormalizationReport:
        return NormalizationReport(self.redacted_fields, self.omitted_fields, self.omitted_candidates)


def _normalize_value(
    value: Any,
    *,
    key: str,
    depth: int,
    limits: PayloadLimits,
    redacted_keys: frozenset[str],
    report: _MutableReport,
) -> Any:
    if key.lower() in redacted_keys:
        report.redacted_fields += 1
        return "[REDACTED]"
    if depth > limits.max_depth:
        report.omitted_fields += 1
        return "[OMITTED:MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > limits.max_string_chars:
            report.omitted_fields += 1
        return value[: limits.max_string_chars]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Enum):
        return _normalize_value(
            value.value,
            key=key,
            depth=depth,
            limits=limits,
            redacted_keys=redacted_keys,
            report=report,
        )
    if isinstance(value, (datetime, UUID, Path)):
        return str(value)
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        items = list(value.items())
        if len(items) > limits.max_collection_items:
            report.omitted_fields += len(items) - limits.max_collection_items
        return {
            str(item_key): _normalize_value(
                item_value,
                key=str(item_key),
                depth=depth + 1,
                limits=limits,
                redacted_keys=redacted_keys,
                report=report,
            )
            for item_key, item_value in items[: limits.max_collection_items]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if isinstance(value, (set, frozenset)):
            items.sort(key=repr)
        if len(items) > limits.max_collection_items:
            report.omitted_fields += len(items) - limits.max_collection_items
        return [
            _normalize_value(
                item,
                key=key,
                depth=depth + 1,
                limits=limits,
                redacted_keys=redacted_keys,
                report=report,
            )
            for item in items[: limits.max_collection_items]
        ]
    report.omitted_fields += 1
    return f"<unsupported:{type(value).__name__}>"


def _candidate_groups(payload: dict[str, Any]):
    for span in payload.get("spans", []):
        yield span.get("outputs", [])
        yield from span.get("input_groups", {}).values()


def _encoded_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def normalize_trace(
    trace: RetrievalTrace,
    *,
    limits: PayloadLimits,
    redacted_keys: frozenset[str],
) -> NormalizedTrace:
    """Return a deterministic, JSON-safe trace or a failed envelope.

    Payload reduction is deliberately limited to candidate detail. Identity,
    topology, timing, and capture metadata are never discarded.
    """
    report = _MutableReport()
    keys = frozenset(key.lower() for key in redacted_keys)
    payload = _normalize_value(
        trace.to_dict(), key="", depth=0, limits=limits, redacted_keys=keys, report=report
    )

    for candidates in _candidate_groups(payload):
        if len(candidates) > limits.max_candidates_per_span:
            report.omitted_candidates += len(candidates) - limits.max_candidates_per_span
            del candidates[limits.max_candidates_per_span :]

    capture = payload.setdefault("capture", {})
    capture["candidates_truncated"] = bool(report.omitted_candidates)
    capture["redacted_field_count"] = report.redacted_fields
    capture["omitted_field_count"] = report.omitted_fields

    if _encoded_size(payload) > limits.max_payload_bytes:
        for candidates in _candidate_groups(payload):
            for candidate in candidates:
                if candidate.pop("metadata", None):
                    report.omitted_fields += 1
        capture["omitted_field_count"] = report.omitted_fields

    if _encoded_size(payload) > limits.max_payload_bytes:
        for candidates in _candidate_groups(payload):
            for candidate in candidates:
                for key in ("text", "content", "page_content"):
                    if candidate.pop(key, None) is not None:
                        report.omitted_fields += 1
        capture["omitted_field_count"] = report.omitted_fields

    failed = _encoded_size(payload) > limits.max_payload_bytes
    return NormalizedTrace(payload=payload, report=report.freeze(), failed=failed)
