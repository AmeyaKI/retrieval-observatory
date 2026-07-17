from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from retrieval_observatory.tracing.integrations._duck_typed import wrap_callable
from retrieval_observatory.tracing.integrations.operator_registry import OperatorRegistry

# Duck-typed OpenAI Agents SDK integration: no import of the `agents` package here, so
# this module stays importable (and unit-testable) without it installed -- see
# _duck_typed.py's module docstring for why. Wraps the plain Python function registered
# as a retrieval tool -- the SDK calls that function directly when the agent invokes the
# tool, so tracing it needs no hook into SDK-internal tool-call lifecycle types.


def wrap_retrieval_tool(
    tool_fn: Callable[..., Any],
    *,
    op_id: Optional[str] = None,
    parent_ids: Sequence[str] = (),
    registry: OperatorRegistry | None = None,
    component_path: str | None = None,
    result_key: Optional[str] = None,
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
) -> Callable[..., Any]:
    """Wrap the function registered as an OpenAI Agents SDK retrieval tool so each
    invocation emits a SOURCE OperatorSpan onto the active retobs trace.

    Usage::

        from agents import function_tool
        import retrieval_observatory as ro
        from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
        from retrieval_observatory.tracing.integrations.openai_agents import wrap_retrieval_tool

        def kb_search(query: str) -> list[dict]:
            return my_index.search(query, k=20)

        kb_search_tool = function_tool(wrap_retrieval_tool(kb_search, op_id="kb_search"))

        start_trace(ObserveContext(run_id="run-1", query_id="q1", query_text=query, pipeline_id="main"))
        # ... run the agent; its retrieval tool call is traced ...
        trace = finish_trace()

    `result_key` is set only if your tool returns a dict/mapping (e.g. `{"results": [...]}}`
    ) rather than a bare list -- leave it unset for a plain list return, the common case.
    Wrap *before* passing to `function_tool(...)` so the SDK's tool schema is derived from
    the original function's signature (the wrapper forwards `*args, **kwargs` transparently).
    """
    return wrap_callable(
        tool_fn,
        op_type="SOURCE",
        op_id=op_id,
        parent_ids=parent_ids,
        registry=registry,
        component_path=component_path or op_id,
        op_name=getattr(tool_fn, "__name__", "retrieval_tool"),
        result_key=result_key,
        deterministic=deterministic,
        replay_policy=replay_policy,
    )
