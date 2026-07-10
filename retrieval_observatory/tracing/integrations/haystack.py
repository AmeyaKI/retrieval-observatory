from __future__ import annotations

from typing import Any, Optional

from retrieval_observatory.tracing.integrations._duck_typed import wrap_callable

# Duck-typed Haystack integration: no import of `haystack` here, so this module stays
# importable (and unit-testable) without the `haystack-ai` package installed -- see
# _duck_typed.py's module docstring for why. Requires only that the passed `component`
# expose a callable `.run` returning a mapping with a "documents" key (the shape every
# Haystack retriever/ranker component returns), per Haystack's Pipeline component contract.


def wrap_haystack_component(
    component: Any,
    *,
    op_type: str = "SOURCE",
    op_id: Optional[str] = None,
    documents_key: str = "documents",
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
) -> Any:
    """Wrap a Haystack component's `run()` so each call emits an OperatorSpan onto the
    active retobs trace (see `retrieval_observatory.sdk.observe.start_trace`).

    Usage::

        import retrieval_observatory as ro
        from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
        from retrieval_observatory.tracing.integrations.haystack import wrap_haystack_component

        retriever = InMemoryBM25Retriever(document_store=store)
        wrap_haystack_component(retriever, op_type="SOURCE", op_id="bm25")
        # retriever is now traced in-place; use it in your Pipeline exactly as before.

        start_trace(ObserveContext(run_id="run-1", query_id="q1", query_text=query, pipeline_id="main"))
        pipeline.run({"retriever": {"query": query}})
        trace = finish_trace()

    Mutates `component.run` in place and returns `component` for chaining. Use
    `op_type="RERANK"` for ranker components. `deterministic`/`replay_policy` default to
    the conservative NOT_REPLAYABLE tier -- pass `deterministic=True,
    replay_policy="EXACT"` only for components you know are exact/reproducible (e.g. a
    pure BM25 retriever), since retobs never fabricates a replay tier it can't verify.
    """
    if not callable(getattr(component, "run", None)):
        raise TypeError(
            f"{component!r} has no callable .run() -- wrap_haystack_component expects a "
            "Haystack Pipeline component."
        )
    component.run = wrap_callable(
        component.run,
        op_type=op_type,
        op_id=op_id,
        op_name=component.__class__.__name__,
        result_key=documents_key,
        deterministic=deterministic,
        replay_policy=replay_policy,
    )
    return component
