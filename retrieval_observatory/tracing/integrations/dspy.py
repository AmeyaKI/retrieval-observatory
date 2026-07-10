from __future__ import annotations

from typing import Any, Callable, Optional

from retrieval_observatory.tracing.integrations._duck_typed import wrap_callable

# Duck-typed DSPy integration: no import of `dspy` here, so this module stays importable
# (and unit-testable) without the `dspy-ai` package installed -- see _duck_typed.py's
# module docstring for why. Requires only that the wrapped callable is DSPy's retrieval
# boundary (`dspy.Retrieve` instance, or any callable returning a `Prediction`-shaped
# object / list) -- retobs never imports `dspy.Retrieve` itself, so it doesn't need to
# track that class's constructor signature across DSPy versions.


def wrap_retrieve(
    retrieve: Callable[..., Any],
    *,
    op_id: Optional[str] = None,
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
) -> Callable[..., Any]:
    """Wrap a DSPy retrieval callable (typically a `dspy.Retrieve(k=...)` instance, or any
    callable returning a `Prediction`-like object with a `.passages` attribute or a plain
    list) so each call emits a SOURCE OperatorSpan onto the active retobs trace.

    Usage::

        import dspy
        import retrieval_observatory as ro
        from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
        from retrieval_observatory.tracing.integrations.dspy import wrap_retrieve

        retrieve = wrap_retrieve(dspy.Retrieve(k=20), op_id="dspy_retrieve")

        start_trace(ObserveContext(run_id="run-1", query_id="q1", query_text=query, pipeline_id="main"))
        result = retrieve(query)
        trace = finish_trace()

    Returns a new callable -- does not mutate `retrieve` in place (DSPy modules are
    typically called via `__call__`, which Python won't let us monkeypatch per-instance
    the way `wrap_haystack_component` patches `.run`).
    """
    return wrap_callable(
        retrieve,
        op_type="SOURCE",
        op_id=op_id,
        op_name=getattr(retrieve, "__class__", type(retrieve)).__name__,
        result_key=None,  # _extract_documents falls back to .passages / list-shaped results
        deterministic=deterministic,
        replay_policy=replay_policy,
    )
