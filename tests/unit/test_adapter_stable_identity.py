from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping
from retrieval_observatory.tracing.integrations.operator_registry import ComponentEvent, OperatorRegistry


def _manifest() -> IntegrationManifest:
    return IntegrationManifest(
        1, "plan", "service", "pipeline",
        (OperatorMapping("dense", "SOURCE", "retriever.dense", "app.py", ("intent_gate",)),),
        {"doc_id": "id"}, (),
    )


def test_same_component_resolves_to_same_operator_across_traces() -> None:
    registry = OperatorRegistry.from_manifest(_manifest())
    first = registry.resolve(ComponentEvent("retriever.dense", "a", ("gate-a",)))
    second = registry.resolve(ComponentEvent("retriever.dense", "b", ("gate-b",)))
    assert first.op_id == second.op_id == "dense"
    assert first.parent_ids == second.parent_ids == ("intent_gate",)
