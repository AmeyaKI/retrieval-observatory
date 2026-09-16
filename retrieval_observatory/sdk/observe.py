from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import sys
import time
import traceback
import uuid
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace, TraceTiming, critical_path_latency_ms

# The active trace is any object with a mutable ``spans`` attribute: a RetrievalTrace started by
# ``start_trace`` or a recorder-managed ``TraceContext`` bound through ``bind_active_trace``. Both
# receive the spans emitted by ``@observe``; only the former is finished by ``finish_trace``.
_current_trace: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "retobs_current_trace", default=None
)
_current_trace_started: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "retobs_current_trace_started", default=None
)

_QUERY_PARAMETERS = ("query", "q", "question", "text")
_log = logging.getLogger("retrieval_observatory")


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


def current_trace() -> Any | None:
    return _current_trace.get()


def bind_active_trace(trace_like: Any) -> Any:
    """Make a recorder-managed trace the target of ``@observe`` spans; returns the previous one.

    A ``TraceContext`` started by ``instrument_fastapi`` or a framework callback lives outside this
    module's contextvar, so decorated functions called inside that request used to record nothing.
    """
    previous = _current_trace.get()
    _current_trace.set(trace_like)
    return previous


def release_active_trace(trace_like: Any, previous: Any = None) -> None:
    """Undo ``bind_active_trace`` if ``trace_like`` is still the active trace."""
    if _current_trace.get() is trace_like:
        _current_trace.set(previous)


def _append(trace: Any, span: OperatorSpan) -> None:
    spans = trace.spans
    if isinstance(spans, list):
        spans.append(span)
    else:
        trace.spans = (*spans, span)


def finish_trace(status: str = "OK", error_traceback: str | None = None) -> RetrievalTrace:
    trace = _current_trace.get()
    if trace is None:
        raise RuntimeError("finish_trace() called without an active trace")
    if not isinstance(trace, RetrievalTrace):
        raise RuntimeError("the active trace is managed by a TraceRecorder and is finished by the recorder, not finish_trace()")
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


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Span params are persisted as JSON; a framework object such as LangChain's
    ``run_manager`` keyword would otherwise make the whole trace unsaveable."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth < 2 and isinstance(value, Mapping):
        return {str(key): _json_safe(item, depth + 1) for key, item in list(value.items())[:50]}
    if depth < 2 and isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item, depth + 1) for item in list(value)[:50]]
    return f"<{type(value).__name__}>"


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
            raw_output = getattr(result, "documents", result)
            output_items = raw_output if isinstance(raw_output, (list, tuple)) else []
            transition = (
                build_candidate_transition(
                    input_groups=groups,
                    output_items=output_items,
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
                    params={key: _json_safe(value) for key, value in kwargs.items() if key not in {"documents", "docs"}},
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


def _query_text_from_call(signature: inspect.Signature | None, args: tuple, kwargs: Mapping[str, Any]) -> str:
    """Best-effort query text for an entrypoint call: a query-named parameter, the first string
    argument, or a query-like attribute of the first argument (a request body model)."""
    values: list[tuple[str, Any]] = []
    if signature is not None:
        try:
            bound = signature.bind_partial(*args, **kwargs)
            values = [(name, value) for name, value in bound.arguments.items() if name not in ("self", "cls")]
        except TypeError:
            values = []
    if not values:
        values = [(f"arg{index}", value) for index, value in enumerate(args)] + list(kwargs.items())
    for name, value in values:
        if name in _QUERY_PARAMETERS and isinstance(value, str):
            return value
    for _name, value in values:
        if isinstance(value, str):
            return value
    for _name, value in values[:1]:
        for attribute in _QUERY_PARAMETERS:
            candidate = getattr(value, attribute, None)
            if isinstance(candidate, str):
                return candidate
    return ""


def _resolve_scope_db_path(db_path: str, module_file: str | None) -> str:
    """A relative db_path is anchored at the integrated project root (the directory holding
    ``retobs/integration.yaml`` above the decorated module), falling back to the working directory.
    ``retobs integrate --phase verify`` resolves the same relative path against the project root."""
    path = Path(db_path)
    if path.is_absolute():
        return str(path)
    if module_file:
        for parent in Path(module_file).resolve().parents:
            if (parent / "retobs" / "integration.yaml").is_file():
                return str(parent / path)
    return str(path)


_pending_persists: set[asyncio.Task[Any]] = set()


async def _persist_trace(trace: RetrievalTrace, db_path: str) -> None:
    try:
        from retrieval_observatory.store.sqlite import SQLiteStore

        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        await store.save_trace(trace)
    except Exception:  # telemetry must never take the application down
        _log.warning("retobs: could not persist trace %s to %s", trace.trace_id, db_path, exc_info=True)


def _persist_trace_sync(trace: RetrievalTrace, db_path: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_persist_trace(trace, db_path))
        return
    task = loop.create_task(_persist_trace(trace, db_path))
    _pending_persists.add(task)
    task.add_done_callback(_pending_persists.discard)


def trace_scope(service_id: str, pipeline_id: str, db_path: str = ".retobs/results.db"):
    """Start, finish, and persist a trace around one entrypoint call.

    Applied by ``retobs integrate --phase apply`` to the project's top entrypoint so that calling
    it records the ``@observe`` operator spans without any further setup. It is a no-op when a
    trace is already active (a ``start_trace`` caller, ``instrument_fastapi``, or a framework
    callback), so it composes with the recorder bridge instead of nesting traces.
    """

    def decorate(fn: Callable[..., Any]):
        try:
            signature: inspect.Signature | None = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None

        def begin(args: tuple, kwargs: Mapping[str, Any]) -> bool:
            if current_trace() is not None:
                return False
            query_text = _query_text_from_call(signature, args, kwargs)
            query_id = sha256(query_text.encode("utf-8")).hexdigest()[:16] if query_text else uuid.uuid4().hex[:16]
            start_trace(ObserveContext(None, query_id, query_text, pipeline_id, service_id))
            return True

        def resolved_db_path() -> str:
            # The code object's filename also covers modules loaded from a path without being
            # registered in sys.modules (``retobs evaluate file.py:symbol`` loads them that way).
            code = getattr(inspect.unwrap(fn), "__code__", None)
            module_file = getattr(code, "co_filename", None)
            if not module_file or not Path(module_file).is_file():
                module = sys.modules.get(getattr(fn, "__module__", "") or "")
                module_file = getattr(module, "__file__", None)
            return _resolve_scope_db_path(db_path, module_file)

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any):
            if not begin(args, kwargs):
                return await fn(*args, **kwargs)
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                await _persist_trace(finish_trace("ERROR", traceback.format_exc()), resolved_db_path())
                raise
            await _persist_trace(finish_trace(), resolved_db_path())
            return result

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any):
            if not begin(args, kwargs):
                return fn(*args, **kwargs)
            try:
                result = fn(*args, **kwargs)
            except Exception:
                _persist_trace_sync(finish_trace("ERROR", traceback.format_exc()), resolved_db_path())
                raise
            _persist_trace_sync(finish_trace(), resolved_db_path())
            return result

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
