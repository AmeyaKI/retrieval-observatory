from __future__ import annotations

import time
from typing import Any, Callable, Optional, Sequence

from retrieval_observatory.sdk.observe import current_trace
from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import OperatorSpan
from retrieval_observatory.tracing.integrations.operator_registry import ComponentEvent, OperatorRegistry

# Shared span-building logic for the duck-typed framework wrappers (Haystack, DSPy,
# OpenAI Agents SDK). "Duck-typed" here means: these wrappers only require the wrapped
# object to be *callable* (a component's .run(), a retrieval function, a tool function) --
# they never import or subclass the target framework's types, so the wrapper modules stay
# importable (and unit-testable) without that framework installed, matching how
# tracing/integrations/langchain.py's classes still import when langchain-core is absent
# (see its _LC_AVAILABLE guard). This trades a formal framework-native integration (e.g.
# implementing Haystack's Tracer ABC) for one that works identically across frameworks and
# needs no per-framework CI extras to test.


def _extract_documents(result: Any, result_key: Optional[str]) -> Sequence[Any]:
    """Pull the list of retrieved documents out of a wrapped call's return value.

    - `result_key` set: `result` is a mapping (e.g. Haystack's {"documents": [...]}))
      and we read that key.
    - `result_key` unset: `result` is itself the document list, or an object exposing a
      `.documents` / `.passages` attribute (covers dspy.Prediction-shaped objects).
    Returns [] (never raises) when the shape doesn't match -- a malformed/unsupported
    result should degrade to "span recorded with no outputs", not crash the caller's
    retrieval call.
    """
    if result is None:
        return []
    if result_key is not None:
        if isinstance(result, dict):
            return result.get(result_key) or []
        return getattr(result, result_key, None) or []
    if isinstance(result, (list, tuple)):
        return result
    for attr in ("documents", "passages"):
        value = getattr(result, attr, None)
        if value is not None:
            return value
    return []


def wrap_callable(
    fn: Callable[..., Any],
    *,
    op_type: str,
    op_id: Optional[str] = None,
    parent_ids: Sequence[str] = (),
    registry: OperatorRegistry | None = None,
    component_path: str | None = None,
    op_name: Optional[str] = None,
    result_key: Optional[str] = None,
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
) -> Callable[..., Any]:
    """Wrap any callable so each call appends an OperatorSpan to the currently active
    trace (`sdk.observe.start_trace()` / `current_trace()`), duck-typed over the return
    value shape via `_extract_documents`. Returns the original result unchanged so the
    wrapped callable's caller sees no behavior difference -- tracing is purely additive.

    If no trace is active (the caller didn't wrap the call in start_trace/finish_trace),
    the call proceeds untraced rather than raising -- tracing must never be a hard
    dependency of the retrieval path itself.
    """
    if registry is None:
        if not op_id:
            raise ValueError("framework tracing requires an explicit op_id or OperatorRegistry binding")
        component_path = component_path or op_id
        registry = OperatorRegistry.explicit(
            component_path=component_path, op_id=op_id, op_type=op_type, parent_ids=tuple(parent_ids)
        )
    if component_path is None:
        raise ValueError("component_path is required with OperatorRegistry")
    resolved = registry.resolve(ComponentEvent(component_path, ""))
    resolved_op_id = resolved.op_id
    op_type = resolved.op_type
    resolved_op_name = op_name or getattr(fn, "__name__", op_type.lower())

    def _record(elapsed_ms: float, result: Any, status: str, error: Optional[str]) -> None:
        trace = current_trace()
        if trace is None:
            return
        documents = _extract_documents(result, result_key) if status == "FIRED" else []
        resolved_parents = resolved.parent_ids
        input_groups = {
            parent: trace.span(parent).outputs for parent in resolved_parents
            if any(span.op_id == parent for span in trace.spans)
        }
        if status == "FIRED":
            transition = build_candidate_transition(
                input_groups=input_groups,
                output_items=documents,
                op_id=resolved_op_id,
                op_type=op_type,
            )
        else:
            transition = None
        span = OperatorSpan(
            op_id=resolved_op_id,
            op_type=op_type,  # type: ignore[arg-type]
            op_name=resolved_op_name,
            parent_ids=resolved_parents,
            status=status,  # type: ignore[arg-type]
            latency_ms=elapsed_ms,
            input_groups=transition.input_groups if transition else input_groups,
            outputs=transition.outputs if transition else (),
            deterministic=deterministic,
            replay_policy=replay_policy,  # type: ignore[arg-type]
            error=error,
        )
        trace.spans = (*trace.spans, span)

    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            _record((time.perf_counter() - start) * 1000, None, "ERROR", str(exc))
            raise
        _record((time.perf_counter() - start) * 1000, result, "FIRED", None)
        return result

    async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            _record((time.perf_counter() - start) * 1000, None, "ERROR", str(exc))
            raise
        _record((time.perf_counter() - start) * 1000, result, "FIRED", None)
        return result

    import inspect

    return _async_wrapper if inspect.iscoroutinefunction(fn) else _sync_wrapper
