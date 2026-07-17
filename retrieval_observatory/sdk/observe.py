from __future__ import annotations

import contextvars
import functools
import time
import uuid
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

import httpx

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace, TraceTiming, critical_path_latency_ms

_current_trace: contextvars.ContextVar[RetrievalTrace | None] = contextvars.ContextVar(
    "retobs_current_trace", default=None
)
_current_trace_started: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "retobs_current_trace_started", default=None
)


@dataclass(frozen=True)
class ObserveContext:
    run_id: str | None
    query_id: str
    query_text: str
    pipeline_id: str
    service_id: str = "default"
    request_id: str | None = None


def start_trace(
    ctx: ObserveContext,
    *,
    metadata: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    pipeline_id: str | None = None,
    query_id: str | None = None,
) -> RetrievalTrace:
    trace = RetrievalTrace(
        uuid.uuid4().hex,
        ctx.service_id,
        ctx.run_id,
        query_id or ctx.query_id,
        ctx.query_text,
        pipeline_id or ctx.pipeline_id,
        (),
        (),
        datetime.now(timezone.utc),
        metadata=dict(metadata or {}),
        request_id=request_id or ctx.request_id,
    )
    _current_trace.set(trace)
    _current_trace_started.set(time.perf_counter())
    return trace


def current_trace() -> RetrievalTrace | None:
    return _current_trace.get()


def _append(trace: RetrievalTrace, span: OperatorSpan) -> None:
    trace.spans = (*trace.spans, span)


def finish_trace(status: str = "OK", error_traceback: str | None = None) -> RetrievalTrace:
    trace = _current_trace.get()
    if trace is None:
        raise RuntimeError("finish_trace() called without an active trace")
    started = _current_trace_started.get()
    wall = (time.perf_counter() - started) * 1000 if started else sum(span.latency_ms for span in trace.spans)
    trace.status = status  # type: ignore[assignment]
    trace.error_traceback = error_traceback
    trace.final_op_ids = (
        tuple(
            span.op_id
            for span in trace.spans
            if span.op_id not in {parent for item in trace.spans for parent in item.parent_ids}
        )
        if status == "OK"
        else ()
    )
    trace.timing = TraceTiming(
        wall, critical_path_latency_ms(trace.spans), sum(span.latency_ms for span in trace.spans)
    )
    _current_trace.set(None)
    _current_trace_started.set(None)
    return trace


def to_candidates(value: Any, op_id: str):
    from retrieval_observatory.tracing.candidates import to_candidates as convert

    return convert(getattr(value, "documents", value), op_id)


def observe(
    op_type: str,
    *,
    op_id: str,
    op_name: str | None = None,
    parent_ids: Sequence[str] = (),
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
    input_variant: str = "raw",
):
    def decorate(fn: Callable[..., Any]):
        def build(result: Any, elapsed: float, status: str, error: str | None, kwargs: dict[str, Any]) -> None:
            trace = current_trace()
            if trace is None:
                return
            groups = {
                parent: span.outputs
                for parent in parent_ids
                if (span := next((item for item in trace.spans if item.op_id == parent), None)) is not None
            }
            observed_parents = tuple(groups)
            transition = (
                build_candidate_transition(
                    input_groups=groups,
                    output_items=getattr(result, "documents", result) or [],
                    op_id=op_id,
                    op_type=op_type,
                )
                if status == "FIRED"
                else None
            )
            _append(
                trace,
                OperatorSpan(
                    op_id,
                    op_type,
                    op_name or fn.__name__,
                    observed_parents,
                    status,
                    elapsed,
                    transition.input_groups if transition else groups,
                    transition.outputs if transition else (),
                    deterministic,
                    replay_policy,
                    input_variant=input_variant,
                    error=error,
                    params={key: value for key, value in kwargs.items() if key not in {"documents", "docs"}},
                ),
            )

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
                build(result, (time.perf_counter() - started) * 1000, "FIRED", None, kwargs)
                return result
            except Exception as exc:
                build(None, (time.perf_counter() - started) * 1000, "ERROR", str(exc), kwargs)
                raise

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                build(result, (time.perf_counter() - started) * 1000, "FIRED", None, kwargs)
                return result
            except Exception as exc:
                build(None, (time.perf_counter() - started) * 1000, "ERROR", str(exc), kwargs)
                raise

        return async_wrapper if iscoroutinefunction(fn) else sync_wrapper

    return decorate


class observe_gate:
    def __init__(self, gate_name: str, fired: bool, gate_values: Mapping[str, Any] | None = None, *, op_id: str):
        self.gate_name, self.fired, self.gate_values, self.op_id = gate_name, fired, dict(gate_values or {}), op_id

    def __enter__(self):
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        trace = current_trace()
        if trace:
            _append(
                trace,
                OperatorSpan(
                    self.op_id,
                    "GATE",
                    self.gate_name,
                    (),
                    "FIRED" if self.fired else "SKIPPED_BY_GATE",
                    (time.perf_counter() - self._started) * 1000,
                    gate_values=self.gate_values,
                ),
            )


async def push_trace(trace: RetrievalTrace, endpoint: str, timeout: float = 5.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=trace.to_dict())
        response.raise_for_status()
        return response.json() if response.content else {"stored": True}
