from tests.unit.test_adapter_stable_identity import _manifest

from retrieval_observatory.tracing.integrations.operator_registry import ComponentEvent, OperatorRegistry


def test_native_run_ids_do_not_replace_declared_parentage() -> None:
    registry = OperatorRegistry.from_manifest(_manifest())
    one = registry.resolve(ComponentEvent("retriever.dense", "dense-1", ("native-parent-1",)))
    two = registry.resolve(ComponentEvent("retriever.dense", "dense-2", ("native-parent-2",)))
    assert one.parent_ids == two.parent_ids == ("intent_gate",)
