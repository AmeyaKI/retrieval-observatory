"""Lets a pipeline tell a runner-imposed timeout apart from any other cancellation.

The benchmark runner bounds every ``pipeline.run`` with ``asyncio.wait_for``, which cancels
the pipeline when the budget runs out. Pipelines convert *that* cancellation into a
``TIMEOUT`` result (keeping partial spans) but must re-raise every other ``CancelledError``
so shutdown and task-group cancellation propagate normally. The runner publishes its
deadline through a context variable; a pipeline consults it when it catches the cancel.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_DEADLINE: ContextVar[float | None] = ContextVar("retobs_pipeline_deadline", default=None)

# Timer handles fire at (or a hair after) their scheduled loop time; allow a little slack.
_SLACK_S = 0.005


@contextmanager
def pipeline_deadline(timeout_s: float) -> Iterator[None]:
    """Declare that the enclosed ``pipeline.run`` is cancelled once ``timeout_s`` elapses."""
    token = _DEADLINE.set(asyncio.get_running_loop().time() + timeout_s)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def cancelled_by_deadline() -> bool:
    """True when a just-caught CancelledError is explained by the published deadline."""
    deadline = _DEADLINE.get()
    if deadline is None:
        return False
    return asyncio.get_running_loop().time() >= deadline - _SLACK_S
