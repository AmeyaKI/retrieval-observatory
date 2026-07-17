import pytest

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.tracing.integrations.dspy import wrap_retrieve
from retrieval_observatory.tracing.integrations.haystack import wrap_haystack_component
from retrieval_observatory.tracing.integrations.openai_agents import wrap_retrieval_tool


class _Component:
    def run(self, query):
        return {"documents": [{"id": "d"}]}


@pytest.mark.parametrize("framework", ["haystack", "dspy", "openai_agents"])
def test_framework_topology_is_stable(framework) -> None:
    if framework == "haystack":
        component = wrap_haystack_component(_Component(), op_id="dense", parent_ids=("intent_gate",))
        def invoke():
            return component.run("query")
    elif framework == "dspy":
        traced = wrap_retrieve(lambda query: [{"id": "d"}], op_id="dense", parent_ids=("intent_gate",))
        def invoke():
            return traced("query")
    else:
        traced = wrap_retrieval_tool(lambda query: [{"id": "d"}], op_id="dense", parent_ids=("intent_gate",))
        def invoke():
            return traced("query")

    signatures = []
    for query_id in ("one", "two"):
        trace = start_trace(ObserveContext("run", query_id, "query", "pipeline"))
        # Parent evidence is supplied by the host graph in real integrations. For this
        # wrapper contract, record a minimal gate before invoking the bound component.
        from retrieval_observatory.tracing.model import OperatorSpan
        trace.spans = (OperatorSpan("intent_gate", "GATE", "gate", (), "FIRED", 0.0),)
        invoke()
        completed = finish_trace()
        signatures.append((completed.span("dense").op_id, completed.span("dense").parent_ids))
    assert signatures == [("dense", ("intent_gate",)), ("dense", ("intent_gate",))]
