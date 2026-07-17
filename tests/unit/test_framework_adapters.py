"""Unit tests for the duck-typed Haystack/DSPy/OpenAI-Agents-SDK adapters
(RETOBS_FINER_PLAN_PHASE2.md, Item E). Deliberately import none of those real packages --
these adapters only require the wrapped object to be callable, so they're testable with
plain stub objects, matching the LangChain/LlamaIndex adapters' CI-without-extras pattern.
"""
from __future__ import annotations

import pytest

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.tracing.integrations.dspy import wrap_retrieve
from retrieval_observatory.tracing.integrations.haystack import wrap_haystack_component
from retrieval_observatory.tracing.integrations.openai_agents import wrap_retrieval_tool


def _ctx():
    return ObserveContext(run_id="r", query_id="q1", query_text="hello", pipeline_id="p")


# --- Haystack ---------------------------------------------------------------

class _StubHaystackRetriever:
    """Stand-in for a Haystack component: exposes .run() returning {"documents": [...]}."""

    def run(self, query: str):
        return {"documents": [{"id": "d1", "score": 0.9}, {"id": "d2", "score": 0.7}]}


def test_wrap_haystack_component_emits_source_span():
    retriever = _StubHaystackRetriever()
    wrap_haystack_component(retriever, op_id="bm25")

    start_trace(_ctx())
    result = retriever.run(query="hello")
    trace = finish_trace()

    assert result == {"documents": [{"id": "d1", "score": 0.9}, {"id": "d2", "score": 0.7}]}
    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.op_type == "SOURCE"
    assert span.op_id == "bm25"
    assert span.status == "FIRED"
    assert {c.doc_id for c in span.outputs} == {"d1", "d2"}


def test_wrap_haystack_component_rejects_non_callable_run():
    with pytest.raises(TypeError):
        wrap_haystack_component(object())


def test_wrap_haystack_component_records_error_span():
    class _Failing:
        def run(self, query: str):
            raise RuntimeError("boom")

    comp = _Failing()
    wrap_haystack_component(comp, op_id="broken")
    start_trace(_ctx())
    with pytest.raises(RuntimeError):
        comp.run(query="x")
    trace = finish_trace()
    assert trace.spans[0].status == "ERROR"
    assert trace.spans[0].error == "boom"


# --- DSPy ---------------------------------------------------------------

class _StubPrediction:
    """Stand-in for dspy.Prediction: exposes .passages."""

    def __init__(self, passages):
        self.passages = passages


class _StubDSPyRetrieve:
    """Stand-in for a dspy.Retrieve instance: callable, returns a Prediction-shaped object."""

    def __call__(self, query: str):
        return _StubPrediction(passages=["passage one", "passage two"])


def test_wrap_retrieve_emits_source_span_from_passages():
    traced = wrap_retrieve(_StubDSPyRetrieve(), op_id="dspy_retrieve")
    start_trace(_ctx())
    result = traced("hello")
    trace = finish_trace()

    assert isinstance(result, _StubPrediction)
    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.op_id == "dspy_retrieve"
    assert span.op_type == "SOURCE"
    assert [c.doc_id for c in span.outputs] == ["passage one", "passage two"]


def test_wrap_retrieve_untraced_without_active_trace():
    # No start_trace() call -- wrapper must not raise, just skip span recording.
    traced = wrap_retrieve(_StubDSPyRetrieve(), op_id="dspy_retrieve")
    result = traced("hello")
    assert isinstance(result, _StubPrediction)


# --- OpenAI Agents SDK ---------------------------------------------------------------

def _kb_search(query: str) -> list:
    return [{"id": "d1", "score": 1.0}]


def test_wrap_retrieval_tool_emits_source_span():
    traced = wrap_retrieval_tool(_kb_search, op_id="kb_search")
    start_trace(_ctx())
    result = traced("hello")
    trace = finish_trace()

    assert result == [{"id": "d1", "score": 1.0}]
    assert len(trace.spans) == 1
    assert trace.spans[0].op_id == "kb_search"
    assert trace.spans[0].outputs[0].doc_id == "d1"


def test_wrap_retrieval_tool_with_result_key():
    def tool(query: str) -> dict:
        return {"results": [{"id": "d1"}]}

    traced = wrap_retrieval_tool(tool, op_id="result_tool", result_key="results")
    start_trace(_ctx())
    traced("hello")
    trace = finish_trace()
    assert trace.spans[0].outputs[0].doc_id == "d1"


@pytest.mark.asyncio
async def test_wrap_retrieval_tool_supports_async_functions():
    async def async_tool(query: str) -> list:
        return [{"id": "async-d1"}]

    traced = wrap_retrieval_tool(async_tool, op_id="async_tool")
    start_trace(_ctx())
    result = await traced("hello")
    trace = finish_trace()
    assert result == [{"id": "async-d1"}]
    assert trace.spans[0].outputs[0].doc_id == "async-d1"
