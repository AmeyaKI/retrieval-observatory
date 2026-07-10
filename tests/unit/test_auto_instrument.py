"""Auto-instrumentation POC (RETOBS_FINER_PLAN_PHASE2.md, Item E). Requires langchain-core,
which is part of this repo's dev extras (langchain), so this test is skipped rather than
failing hard if it's absent."""
from __future__ import annotations

import pytest

langchain_core = pytest.importorskip("langchain_core")

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.tracing.auto_instrument import auto_instrument, stop_auto_instrument


def _make_retriever():
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever

    class _FixedRetriever(BaseRetriever):
        def _get_relevant_documents(self, query, *, run_manager=None):
            return [Document(page_content="doc one", metadata={"id": "d1"}),
                   Document(page_content="doc two", metadata={"id": "d2"})]

    return _FixedRetriever()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    stop_auto_instrument()


def test_auto_instrument_traces_without_manual_callback():
    retriever = _make_retriever()
    auto_instrument("langchain")

    start_trace(ObserveContext(run_id="r", query_id="q1", query_text="hello", pipeline_id="p"))
    docs = retriever.invoke("hello")  # no callbacks=[...] anywhere in this call
    trace = finish_trace()

    assert len(docs) == 2
    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.op_type == "SOURCE"
    assert span.status == "FIRED"
    assert len(span.outputs) == 2


def test_stop_auto_instrument_restores_original_method():
    from langchain_core.retrievers import BaseRetriever

    original = BaseRetriever.invoke
    auto_instrument("langchain")
    assert BaseRetriever.invoke is not original
    stop_auto_instrument()
    assert BaseRetriever.invoke is original


def test_auto_instrument_is_idempotent():
    auto_instrument("langchain")
    patched_once = _make_retriever().__class__.invoke
    auto_instrument("langchain")  # calling twice must not double-wrap
    patched_twice = _make_retriever().__class__.invoke
    assert patched_once is patched_twice


def test_auto_instrument_rejects_unsupported_framework():
    with pytest.raises(ValueError):
        auto_instrument("haystack")


def test_untraced_without_active_trace():
    retriever = _make_retriever()
    auto_instrument("langchain")
    # No start_trace() -- must not raise.
    docs = retriever.invoke("hello")
    assert len(docs) == 2
