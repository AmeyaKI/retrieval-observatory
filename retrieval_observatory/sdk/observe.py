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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.capture import (
    _CANDIDATE_PARAMETERS,
    CaptureError,
    CaptureFailure,
    CaptureSpec,
    bind_arguments,
    capture_is_strict,
    default_input_groups,
    extract_outputs,
    incomplete_boundary_count,
    snapshot,
    source_ref,
)
from retrieval_observatory.tracing.lineage_contract import ParentLinkage
from retrieval_observatory.tracing.model import (
    Candidate,
    InputCapture,
    OperatorSpan,
    OutputCapture,
    RetrievalTrace,
    TraceTiming,
    critical_path_latency_ms,
    latest_span_of,
    next_node_id,
)

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
    trace.capture = replace(trace.capture, incomplete_boundary_count=incomplete_boundary_count(trace.spans))
    _current_trace.set(None)
    _current_trace_started.set(None)
    return trace


def to_candidates(value: Any, op_id: str):
    from retrieval_observatory.tracing.candidates import to_candidates as convert

    return convert(getattr(value, "documents", value), op_id)


def record_return_boundary(trace: Any, returned: Sequence[Any] | None, *, error: str | None = None) -> None:
    """Append what an entrypoint returned as the trace's final boundary: a ``return`` TRANSFORM
    span fed by the sink operator(s), with ``params={"boundary": "callable_return"}``.

    Skipped when the returned ids are exactly what the sinks emitted, or exactly what one sink
    emitted (a plan that has not declared an edge yet still has the last operator's output as
    the final boundary): the sinks already are the final boundary. Otherwise the span records
    what left the callable after its last observed operator (an untraced post-filter, a
    failure). ``returned`` is the returned sequence of candidate-like items, or ``None`` when
    nothing usable was returned.
    """
    spans = tuple(trace.spans)
    parents = {parent for span in spans for parent in span.parent_ids}
    sinks = [span for span in spans if span.op_id not in parents]
    node_id = next_node_id((span.op_id for span in spans), "return")
    outputs = () if returned is None else tuple(to_candidates(list(returned), node_id))
    returned_ids = [c.doc_id for c in outputs]
    if error is None and returned is not None and (
        [c.doc_id for span in sinks for c in span.outputs] == returned_ids
        or any([c.doc_id for c in span.outputs] == returned_ids for span in sinks)
    ):
        return
    _append(
        trace,
        OperatorSpan(
            node_id,
            "TRANSFORM",
            "returned result",
            tuple(span.op_id for span in sinks),
            "ERROR" if error else "FIRED",
            0.0,
            input_groups={span.op_id: span.outputs for span in sinks},
            outputs=outputs,
            params={"boundary": "callable_return"},
            error=error,
            input_capture="inferred" if sinks else "not_applicable",
            output_capture="unavailable" if error or returned is None else "recorded",
            operator_id="return",
            parent_linkage="declared",
        ),
    )


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


@dataclass
class _Invocation:
    """Per-call capture state shared between the pre-call and post-call halves of the wrapper."""

    invocation_id: str
    trace: Any
    kwargs: Mapping[str, Any]
    node_id: str
    bound: inspect.BoundArguments | None = None
    # Node keys of the resolved parent spans, in declared order, and their invocation ids.
    observed_parents: tuple[str, ...] = ()
    parent_invocation_ids: tuple[str, ...] = ()
    parent_linkage: ParentLinkage = "recorded"
    groups: dict[str, tuple[Candidate, ...]] = field(default_factory=dict)
    input_capture: InputCapture = "not_applicable"
    failures: list[CaptureFailure] = field(default_factory=list)
    # Keyword arguments whose values supplied the captured input candidates (never copied into params).
    input_arguments: set[str] = field(default_factory=set)


def _append_failures(trace: Any, failures: Sequence[CaptureFailure]) -> None:
    if not failures:
        return
    recorded = [failure.to_dict() for failure in failures]
    existing = getattr(trace, "capture_failures", ())
    if isinstance(existing, list):
        existing.extend(recorded)
    else:
        trace.capture_failures = (*existing, *recorded)


def _arguments_supplying(kwargs: Mapping[str, Any], groups: Mapping[str, Sequence[Any]]) -> set[str]:
    """Keyword arguments that hold a captured input group or one of its items (directly, or in a list or mapping)."""
    supplied = {id(group) for group in groups.values()} | {id(item) for group in groups.values() for item in group}

    def holds(value: Any, depth: int = 0) -> bool:
        if id(value) in supplied:
            return True
        if depth < 2 and isinstance(value, (list, tuple)):
            return any(holds(item, depth + 1) for item in value)
        if depth < 2 and isinstance(value, Mapping):
            return any(holds(item, depth + 1) for item in value.values())
        return False

    return {name for name, value in kwargs.items() if holds(value)}


def _gate_decision(result: Any) -> dict[str, Any] | None:
    """The route a GATE returned: a string (or bool) is ``selected_route``; a mapping of scalars is
    taken as the gate's values; anything else (a candidate list) is not a decision."""
    if isinstance(result, (str, bool)):
        return {"selected_route": result}
    if isinstance(result, Mapping) and result and all(
        item is None or isinstance(item, (str, bool, int, float)) for item in result.values()
    ):
        return {str(key): item for key, item in result.items()}
    return None


def _error_text(exc: BaseException) -> str:
    return "cancelled" if isinstance(exc, asyncio.CancelledError) else f"{type(exc).__name__}: {exc}"


def observe(
    op_type: str,
    *,
    op_id: str,
    op_name: str | None = None,
    parent_ids: Sequence[str] = (),
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
    input_variant: str = "raw",
    capture: CaptureSpec | None = None,
):
    """Record one operator span per call from the call's ACTUAL boundary.

    Inputs are the bound arguments snapshotted before the call and outputs are the returned
    object; parent-span outputs are used only as a fallback and labelled ``inferred``. The
    wrapped function is called exactly once, its result is returned unchanged, its exceptions
    propagate untouched, and capture failures are recorded on the trace instead of raised.
    """
    declared_parents = tuple(parent_ids)
    candidate_arguments = {*_CANDIDATE_PARAMETERS, *declared_parents}

    def decorate(fn: Callable[..., Any]):
        ref = source_ref(fn)

        def fail(inv: _Invocation, phase: str, code: str, detail: str) -> None:
            inv.failures.append(CaptureFailure(inv.node_id, inv.invocation_id, phase, code, detail))

        def begin(args: tuple, kwargs: dict[str, Any]) -> _Invocation:
            inv = _Invocation(uuid.uuid4().hex, current_trace(), kwargs, op_id)
            if inv.trace is None:
                return inv
            inv.bound = bind_arguments(fn, args, kwargs)
            spans = tuple(inv.trace.spans)
            inv.node_id = next_node_id((span.op_id for span in spans), op_id)
            # A declared parent names an operator; its inputs came from that operator's latest invocation.
            parent_spans = {
                parent: span for parent in declared_parents if (span := latest_span_of(spans, parent)) is not None
            }
            inv.observed_parents = tuple(span.op_id for span in parent_spans.values())
            invocation_ids = tuple(span.invocation_id for span in parent_spans.values())
            inv.parent_invocation_ids = invocation_ids if all(invocation_ids) else ()  # type: ignore[assignment]
            # A GATE parent hands down a decision, not candidates: it stays a topology edge but is
            # not an input group, so a source routed by a gate still has ``not_applicable`` inputs.
            candidate_parents = tuple(
                parent for parent in declared_parents
                if parent not in parent_spans or parent_spans[parent].op_type != "GATE"
            )
            candidate_spans = {parent: span for parent, span in parent_spans.items() if parent in candidate_parents}
            try:
                if not candidate_parents:
                    groups, inv.input_capture = None, "not_applicable"
                elif capture is not None and capture.inputs is not None:
                    groups = capture.inputs(inv.bound)
                    inv.input_capture = "unavailable" if groups is None else "recorded"
                    if groups is not None and set(groups) - set(declared_parents):
                        fail(inv, "inputs", "undeclared_input_group", repr(sorted(set(groups) - set(declared_parents))))
                        groups, inv.input_capture = None, "unavailable"
                else:
                    groups, inv.input_capture = default_input_groups(inv.bound, candidate_parents)
                if groups is not None:
                    inv.input_arguments = _arguments_supplying(inv.kwargs, groups)
                    inv.parent_linkage = "declared"
                    for parent, items in groups.items():
                        if parent in parent_spans:
                            node = parent_spans[parent].op_id
                            inv.groups[node] = tuple(snapshot(items, node))
                        else:
                            # Real inputs arrived from an operator this trace never observed; a span
                            # cannot reference a missing parent, so the link is recorded as lost.
                            fail(inv, "inputs", "producer_not_observed", f"{parent}: {len(items)} candidates")
                            inv.parent_linkage = "unavailable"
                elif inv.input_capture == "unavailable" and candidate_spans and not inv.failures:
                    # No actual inputs could be read: reconstruct them from the parent spans, labelled
                    # so. A failed mapping is recorded instead of papered over.
                    inv.groups = {span.op_id: tuple(span.outputs) for span in candidate_spans.values()}
                    inv.input_capture, inv.parent_linkage = "inferred", "inferred"
                elif candidate_parents:
                    inv.parent_linkage = "unavailable"
            except Exception as exc:
                fail(inv, "inputs", "input_mapping_failed", repr(exc))
                inv.groups, inv.input_capture, inv.parent_linkage = {}, "unavailable", "unavailable"
            return inv

        def complete(inv: _Invocation, result: Any, elapsed: float, status: str, error: str | None) -> None:
            if inv.trace is None:
                return
            groups: Mapping[str, tuple[Candidate, ...]] = inv.groups
            outputs: tuple[Candidate, ...] = ()
            output_capture: OutputCapture = "unavailable"
            gate_values: dict[str, Any] = {}
            if status == "FIRED":
                items: Sequence[Any] | None = None
                try:
                    if capture is not None and capture.outputs is not None:
                        items = capture.outputs(result)
                        if items is None:
                            fail(inv, "outputs", "output_mapping_returned_none", type(result).__name__)
                    elif op_type == "GATE" and (decision := _gate_decision(result)) is not None:
                        # A gate emits a decision, not candidates: the route it selected is the
                        # recorded output, and no candidate list is invented.
                        gate_values, items, output_capture = decision, [], "recorded"
                    else:
                        items, output_capture, code = extract_outputs(result)
                        if code is not None:
                            fail(inv, "outputs", code, type(result).__name__)
                except Exception as exc:
                    fail(inv, "outputs", "output_mapping_failed", repr(exc))
                    items = None
                decisions: Mapping[str, Any] | None = None
                if capture is not None and capture.decisions is not None:
                    try:
                        decisions = dict(capture.decisions(inv.bound, result))
                    except Exception as exc:
                        fail(inv, "decisions", "decision_mapping_failed", repr(exc))
                if items is not None:
                    try:
                        transition = build_candidate_transition(
                            input_groups=inv.groups,
                            output_items=list(items),
                            op_id=inv.node_id,
                            op_type=op_type,
                            decision_reasons=decisions,
                        )
                        groups, outputs, output_capture = transition.input_groups, transition.outputs, "recorded"
                    except Exception as exc:
                        fail(inv, "outputs", "output_mapping_failed", repr(exc))
                        groups, outputs, output_capture = inv.groups, (), "unavailable"
            # Candidate arguments are lineage, not configuration: never copy their content into params.
            params = {
                key: _json_safe(value)
                for key, value in inv.kwargs.items()
                if key not in candidate_arguments and key not in inv.input_arguments
            }

            def span(groups: Mapping[str, tuple[Candidate, ...]], outputs: tuple[Candidate, ...], input_capture: str, output_capture: str) -> OperatorSpan:
                return OperatorSpan(
                    inv.node_id,
                    op_type,
                    op_name or fn.__name__,
                    inv.observed_parents,
                    status,
                    elapsed,
                    groups,
                    outputs,
                    deterministic,
                    replay_policy,
                    input_variant=input_variant,
                    error=error,
                    params=params,
                    gate_values=gate_values,
                    invocation_id=inv.invocation_id,
                    input_capture=input_capture,
                    output_capture=output_capture,
                    source_ref=ref,
                    operator_id=op_id,
                    parent_invocation_ids=inv.parent_invocation_ids,
                    parent_linkage=inv.parent_linkage,
                )

            try:
                recorded = span(groups, outputs, inv.input_capture, output_capture)
            except Exception as exc:  # e.g. duplicate candidate IDs in the application's own lists
                fail(inv, "outputs", "span_build_failed", repr(exc))
                recorded = span({}, (), "unavailable", "unavailable")
            _append(inv.trace, recorded)
            _append_failures(inv.trace, inv.failures)
            if status == "FIRED" and inv.failures and capture_is_strict():
                raise CaptureError(
                    f"{inv.node_id}: " + "; ".join(f"{failure.phase}/{failure.code}: {failure.detail}" for failure in inv.failures)
                )

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any):
            inv = begin(args, kwargs)
            started = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
            except BaseException as exc:
                complete(inv, None, (time.perf_counter() - started) * 1000, "ERROR", _error_text(exc))
                raise
            complete(inv, result, (time.perf_counter() - started) * 1000, "FIRED", None)
            return result

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any):
            inv = begin(args, kwargs)
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                complete(inv, None, (time.perf_counter() - started) * 1000, "ERROR", _error_text(exc))
                raise
            complete(inv, result, (time.perf_counter() - started) * 1000, "FIRED", None)
            return result

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

        def record_result(result: Any) -> None:
            """The entrypoint's return value is the final boundary; an unreadable shape is a
            recorded capture failure, never an invented output and never an exception."""
            trace = current_trace()
            items, _, code = extract_outputs(result)
            if items is None:
                detail = f"{type(result).__name__}: {code}"
                _append_failures(trace, [CaptureFailure("return", None, "outputs", "final_output_shape_unsupported", detail)])
                return
            try:
                record_return_boundary(trace, items)
            except Exception as exc:  # e.g. duplicate candidate IDs in the returned list
                _append_failures(trace, [CaptureFailure("return", None, "outputs", "span_build_failed", repr(exc))])

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any):
            if not begin(args, kwargs):
                return await fn(*args, **kwargs)
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                await _persist_trace(finish_trace("ERROR", traceback.format_exc()), resolved_db_path())
                raise
            record_result(result)
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
            record_result(result)
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
