"""Boundary capture for ``@observe``: an operator's actual bound arguments and returned object.

Everything here is observational. Nothing consumes, copies deeply, or mutates application
objects, and nothing raises into the application except ``CaptureError`` under
``strict_capture()``, after the wrapped call has completed.
"""
from __future__ import annotations

import contextlib
import contextvars
import inspect
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from retrieval_observatory.tracing.candidates import to_candidates
from retrieval_observatory.tracing.model import Candidate, InputCapture, OperatorSpan, OutputCapture


@dataclass(frozen=True)
class CaptureSpec:
    """Optional per-operator mappings from the call boundary to candidate sequences.

    ``inputs`` maps bound arguments to ``{parent_id: candidates}``; ``outputs`` maps the returned
    object to its candidates; ``decisions`` maps the call to ``{candidate_id: decision_reason}``.
    """

    inputs: Callable[[inspect.BoundArguments | None], Mapping[str, Sequence[Any]] | None] | None = None
    outputs: Callable[[Any], Sequence[Any] | None] | None = None
    decisions: Callable[[inspect.BoundArguments | None, Any], Mapping[str, Any]] | None = None


class CaptureError(RuntimeError):
    """Raised only under ``strict_capture()``, after the application call completed."""


@dataclass(frozen=True)
class CaptureFailure:
    op_id: str
    invocation_id: str | None
    phase: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CANDIDATE_PARAMETERS = ("documents", "docs", "candidates", "hits", "results", "passages", "chunks", "items", "lanes")
_COMPLETE_INPUT_CAPTURE = {"recorded", "not_applicable"}
_strict: contextvars.ContextVar[bool] = contextvars.ContextVar("retobs_strict_capture", default=False)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def bind_arguments(fn: Callable[..., Any], args: Sequence[Any], kwargs: Mapping[str, Any]) -> inspect.BoundArguments | None:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    for bind in (signature.bind, signature.bind_partial):
        try:
            return bind(*args, **kwargs)
        except TypeError:
            continue
    return None


def default_input_groups(
    bound: inspect.BoundArguments | None, parent_ids: Sequence[str]
) -> tuple[Mapping[str, Sequence[Any]] | None, InputCapture]:
    """Match declared parents to the operator's actual arguments without a ``CaptureSpec``."""
    parent_ids = tuple(parent_ids)
    if not parent_ids:
        return None, "not_applicable"
    arguments = {} if bound is None else {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
    if all(_is_sequence(arguments.get(parent)) for parent in parent_ids):
        return {parent: arguments[parent] for parent in parent_ids}, "recorded"
    if len(parent_ids) == 1:
        named = [name for name in _CANDIDATE_PARAMETERS if _is_sequence(arguments.get(name))]
        if len(named) != 1:
            named = [name for name, value in arguments.items() if _is_sequence(value)]
        if len(named) == 1:
            return {parent_ids[0]: arguments[named[0]]}, "recorded"
    lanes = [
        value
        for value in arguments.values()
        if _is_sequence(value) and len(value) == len(parent_ids) and all(_is_sequence(item) for item in value)
    ]
    if len(lanes) == 1:
        return dict(zip(parent_ids, lanes[0])), "positional"
    return None, "unavailable"


def _is_iterator(value: Any) -> bool:
    if inspect.isgenerator(value):
        return True
    return hasattr(value, "__next__") and not isinstance(value, (list, tuple, str, bytes, Mapping))


_OUTPUT_KEYS = ("documents", "docs", "candidates", "hits", "results")


def extract_outputs(result: Any) -> tuple[Sequence[Any] | None, OutputCapture, str | None]:
    """The returned candidates, or why they could not be read. An iterator is never consumed.

    A mapping yields the first present key of ``_OUTPUT_KEYS`` whose value is a list or tuple
    (a response body such as ``{"hits": [...], "took_ms": 3}``)."""
    if isinstance(result, Mapping):
        for key in _OUTPUT_KEYS:
            if key in result and _is_sequence(result[key]):
                return result[key], "recorded", None
    items = getattr(result, "documents", result)
    if _is_sequence(items):
        return items, "recorded", None
    if _is_iterator(items):
        return None, "unavailable", "iterator_output_not_captured"
    return None, "unavailable", "unsupported_output_shape"


def snapshot(items: Sequence[Any], op_id: str) -> list[Candidate]:
    """Candidates from a shallow copy taken now, so later in-place mutation cannot change ranks."""
    return to_candidates(list(items), op_id)


def source_ref(fn: Callable[..., Any]) -> str | None:
    try:
        code = inspect.unwrap(fn).__code__
        path = Path(code.co_filename)
        try:
            path = path.relative_to(Path.cwd())
        except ValueError:
            pass
        return f"{path}:{code.co_firstlineno}:{fn.__qualname__}"
    except Exception:
        return None


def incomplete_boundary_count(spans: Sequence[OperatorSpan]) -> int:
    return sum(
        1
        for span in spans
        if span.input_capture not in _COMPLETE_INPUT_CAPTURE or span.output_capture != "recorded"
    )


@contextlib.contextmanager
def strict_capture() -> Iterator[None]:
    """Turn capture failures into ``CaptureError`` (raised after the application call)."""
    token = _strict.set(True)
    try:
        yield
    finally:
        _strict.reset(token)


def capture_is_strict() -> bool:
    return _strict.get()
