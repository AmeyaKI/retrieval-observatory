from __future__ import annotations

from typing import Any, Optional

from retrieval_observatory.sdk.observe import to_candidates

# Auto-instrumentation proof of concept (RETOBS_FINER_PLAN_PHASE2.md, Item E): patches
# LangChain's BaseRetriever.invoke at the class level so every retriever call is traced
# automatically -- no per-call site needs `callbacks=[cb]` or an `@observe`-wrapped
# function, matching the vision's "the fewer manual callbacks users write, the more likely
# they are to adopt" goal.
#
# This is global, process-wide monkeypatch state -- exactly the kind of surprising
# behavior the Trust principle warns against. It is therefore never applied at import
# time: it only activates when `auto_instrument("langchain")` is called explicitly, and
# `stop_auto_instrument()` restores the original method. See
# docs/guides/auto-instrumentation.md for the trade-off writeup.

_original_invoke: Optional[Any] = None
_original_ainvoke: Optional[Any] = None
_patched_class: Optional[type] = None


def _record_span(op_id: str, op_name: str, elapsed_ms: float, result: Any, status: str, error: Optional[str]) -> None:
    from retrieval_observatory.sdk.observe import current_trace
    from retrieval_observatory.tracing.model import OperatorSpan

    trace = current_trace()
    if trace is None:
        return
    documents = result if status == "FIRED" and isinstance(result, list) else []
    trace.spans = (*trace.spans, OperatorSpan(
            op_id=op_id,
            op_type="SOURCE",
            op_name=op_name,
            parent_ids=[trace.spans[-1].op_id] if trace.spans else [],
            status=status,  # type: ignore[arg-type]
            deterministic=False,
            replay_policy="NOT_REPLAYABLE",
            latency_ms=elapsed_ms,
            outputs=to_candidates(documents, op_id),
            error=error,
        ))


def _patch_langchain() -> None:
    global _original_invoke, _original_ainvoke, _patched_class
    if _patched_class is not None:
        return  # already patched -- idempotent
    try:
        from langchain_core.retrievers import BaseRetriever
    except ImportError as exc:
        raise ImportError(
            "auto_instrument('langchain') requires langchain-core. "
            "Install with: pip install retrieval-observatory[langchain]"
        ) from exc

    import time

    original_invoke = BaseRetriever.invoke
    original_ainvoke = BaseRetriever.ainvoke

    def _traced_invoke(self, input, config=None, **kwargs):  # noqa: A002
        op_id = f"source_{self.__class__.__name__}"
        start = time.perf_counter()
        try:
            result = original_invoke(self, input, config=config, **kwargs)
        except Exception as exc:
            _record_span(op_id, self.__class__.__name__, (time.perf_counter() - start) * 1000, None, "ERROR", str(exc))
            raise
        _record_span(op_id, self.__class__.__name__, (time.perf_counter() - start) * 1000, result, "FIRED", None)
        return result

    async def _traced_ainvoke(self, input, config=None, **kwargs):  # noqa: A002
        op_id = f"source_{self.__class__.__name__}"
        start = time.perf_counter()
        try:
            result = await original_ainvoke(self, input, config=config, **kwargs)
        except Exception as exc:
            _record_span(op_id, self.__class__.__name__, (time.perf_counter() - start) * 1000, None, "ERROR", str(exc))
            raise
        _record_span(op_id, self.__class__.__name__, (time.perf_counter() - start) * 1000, result, "FIRED", None)
        return result

    _original_invoke = original_invoke
    _original_ainvoke = original_ainvoke
    _patched_class = BaseRetriever
    BaseRetriever.invoke = _traced_invoke
    BaseRetriever.ainvoke = _traced_ainvoke


def auto_instrument(framework: str) -> None:
    """Globally auto-trace every retriever call for `framework`, with zero per-call-site
    code. Currently supports only "langchain" (proof of concept -- see module docstring
    for the global-state trade-off this makes). Must be called explicitly; never applied
    as an import-time side effect.
    """
    if framework != "langchain":
        raise ValueError(f"auto_instrument currently only supports 'langchain', got {framework!r}")
    _patch_langchain()


def stop_auto_instrument() -> None:
    """Undo `auto_instrument()`, restoring the original (un-traced) methods."""
    global _original_invoke, _original_ainvoke, _patched_class
    if _patched_class is None:
        return
    _patched_class.invoke = _original_invoke
    _patched_class.ainvoke = _original_ainvoke
    _original_invoke = None
    _original_ainvoke = None
    _patched_class = None
