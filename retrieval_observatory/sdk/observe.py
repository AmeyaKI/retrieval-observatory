from __future__ import annotations

import contextvars
import functools
import time
import uuid
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from retrieval_observatory.tracing.model_v2 import (
    Candidate,
    OperatorSpan,
    RetrievalTraceV2,
    TraceTiming,
    critical_path_latency_ms,
)
from retrieval_observatory.tracing.candidates import (
    build_candidate_transition,
    clone_candidate,
    to_candidates as _candidate_list,
)

_current_trace: contextvars.ContextVar[RetrievalTraceV2 | None] = contextvars.ContextVar(
    "retobs_current_trace",
    default=None,
)
_current_trace_started: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "retobs_current_trace_started",
    default=None,
)


@dataclass
class ObserveContext:
    run_id: str
    query_id: str
    query_text: str
    pipeline_id: str
    request_id: Optional[str] = None


def start_trace(
    ctx: ObserveContext,
    *,
    metadata: Dict[str, Any] | None = None,
    request_id: str | None = None,
    pipeline_id: str | None = None,
    query_id: str | None = None,
) -> RetrievalTraceV2:
    trace = RetrievalTraceV2(
        trace_id=uuid.uuid4().hex,
        run_id=ctx.run_id,
        query_id=query_id or ctx.query_id,
        query_text=ctx.query_text,
        pipeline_id=pipeline_id or ctx.pipeline_id,
        spans=[],
        total_latency_ms=0.0,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata or {},
        request_id=request_id or ctx.request_id,
    )
    _current_trace.set(trace)
    _current_trace_started.set(time.perf_counter())
    return trace


def current_trace() -> RetrievalTraceV2 | None:
    """The active trace started by `start_trace()`, if any -- used by duck-typed framework
    wrappers (tracing/integrations/{haystack,dspy,openai_agents}.py) to append spans
    without each wrapper needing its own context-passing convention."""
    return _current_trace.get()


def finish_trace(status: str = "OK", error_traceback: str | None = None) -> RetrievalTraceV2:
    trace = _current_trace.get()
    if trace is None:
        raise RuntimeError("finish_trace() called without an active trace")
    trace.status = status  # type: ignore[assignment]
    trace.error_traceback = error_traceback
    started = _current_trace_started.get()
    operator_sum_ms = sum(max(0.0, span.latency_ms) for span in trace.spans)
    wall_clock_ms = (time.perf_counter() - started) * 1000 if started is not None else operator_sum_ms
    trace.total_latency_ms = wall_clock_ms
    trace.timing = TraceTiming(
        wall_clock_ms=wall_clock_ms,
        critical_path_ms=critical_path_latency_ms(trace.spans),
        operator_sum_ms=operator_sum_ms,
    )
    if trace.final_op_id is None and trace.spans:
        parent_ids = {parent for span in trace.spans for parent in span.parent_ids}
        sinks = [span.op_id for span in trace.spans if span.op_id not in parent_ids]
        trace.final_op_id = sinks[0] if len(sinks) == 1 else None
    return trace


def _to_candidates(value: Any, op_id: str) -> List[Candidate]:
    documents = getattr(value, "documents", value)
    return _candidate_list(documents, op_id)


# Public alias: framework wrappers outside this module reuse the same duck-typed
# document->Candidate coercion (objects with .doc_id/.id, dicts, or plain strings) rather
# than reimplementing it per framework.
to_candidates = _to_candidates


def observe(
    op_type: str,
    *,
    op_id: str | None = None,
    op_name: str | None = None,
    parent_ids: List[str] | None = None,
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
    input_variant: str = "raw",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _build_span(
            trace: RetrievalTraceV2 | None,
            resolved_op_id: str,
            resolved_parent_ids: List[str],
            elapsed: float,
            result: Any,
            status: str,
            err: str | None,
            kwargs: Dict[str, Any],
        ) -> None:
            if trace is None:
                return
            spans_by_id = {span.op_id: span for span in trace.spans}
            input_groups = {
                parent_id: spans_by_id[parent_id].outputs
                for parent_id in resolved_parent_ids
                if parent_id in spans_by_id
            }
            provided_inputs = kwargs.get("documents") or kwargs.get("docs")
            if not input_groups and provided_inputs:
                input_groups = {"provided": _to_candidates(provided_inputs, op_id=resolved_op_id)}
            if status == "FIRED":
                inputs, outputs = build_candidate_transition(
                    input_groups=input_groups,
                    output_items=getattr(result, "documents", result) or [],
                    op_id=resolved_op_id,
                    op_type=op_type,
                )
            else:
                inputs = [
                    clone_candidate(candidate)
                    for candidates in input_groups.values()
                    for candidate in candidates
                ]
                outputs = []
            trace.spans.append(
                OperatorSpan(
                    op_id=resolved_op_id,
                    op_type=op_type,  # type: ignore[arg-type]
                    op_name=op_name or fn.__name__,
                    parent_ids=list(resolved_parent_ids),
                    status=status,  # type: ignore[arg-type]
                    deterministic=deterministic,
                    replay_policy=replay_policy,  # type: ignore[arg-type]
                    latency_ms=elapsed,
                    inputs=inputs,
                    outputs=outputs,
                    params={k: v for k, v in kwargs.items() if k not in {"documents", "docs"}},
                    input_variant=input_variant,
                    error=err,
                )
            )

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            trace = _current_trace.get()
            start = time.perf_counter()
            resolved_parents = kwargs.pop("parent_ids", None) or parent_ids or (
                [trace.spans[-1].op_id] if trace and trace.spans else []
            )
            resolved_id = kwargs.pop("op_id", None) or op_id or f"{op_type.lower()}_{uuid.uuid4().hex[:8]}"
            try:
                result = await fn(*args, **kwargs)
                status = "FIRED"
                err = None
            except Exception as exc:
                result = None
                status = "ERROR"
                err = str(exc)
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                _build_span(trace, resolved_id, resolved_parents, elapsed, result, status, err, kwargs)
            return result

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            trace = _current_trace.get()
            start = time.perf_counter()
            resolved_parents = kwargs.pop("parent_ids", None) or parent_ids or (
                [trace.spans[-1].op_id] if trace and trace.spans else []
            )
            resolved_id = kwargs.pop("op_id", None) or op_id or f"{op_type.lower()}_{uuid.uuid4().hex[:8]}"
            try:
                result = fn(*args, **kwargs)
                status = "FIRED"
                err = None
            except Exception as exc:
                result = None
                status = "ERROR"
                err = str(exc)
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                _build_span(trace, resolved_id, resolved_parents, elapsed, result, status, err, kwargs)
            return result

        return async_wrapper if iscoroutinefunction(fn) else sync_wrapper

    return decorator


class observe_gate:
    def __init__(self, gate_name: str, fired: bool, gate_values: Dict[str, Any] | None = None):
        self.gate_name = gate_name
        self.fired = fired
        self.gate_values = gate_values or {}
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        trace = _current_trace.get()
        if trace is None:
            return
        elapsed = (time.perf_counter() - self._start) * 1000
        trace.spans.append(
            OperatorSpan(
                op_id=f"gate_{uuid.uuid4().hex[:8]}",
                op_type="GATE",
                op_name=self.gate_name,
                parent_ids=[trace.spans[-1].op_id] if trace.spans else [],
                status="FIRED" if self.fired else "SKIPPED_BY_GATE",
                deterministic=True,
                replay_policy="NOT_REPLAYABLE",
                latency_ms=elapsed,
                gate_values=self.gate_values,
            )
        )


async def push_trace(trace: RetrievalTraceV2, endpoint: str, timeout: float = 5.0) -> Dict[str, Any]:
    payload = trace.to_dict()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        return response.json() if response.content else {"stored": True}
