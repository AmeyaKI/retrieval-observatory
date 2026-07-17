from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping


class UnmappedOperatorError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentEvent:
    path: str
    run_id: str
    parent_run_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperatorBinding:
    component_path: str
    op_id: str
    op_type: str
    parent_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, item: OperatorMapping) -> "OperatorBinding":
        path = item.symbol or item.relative_path
        return cls(path, item.op_id, item.op_type, tuple(item.parent_ids))


@dataclass(frozen=True)
class ResolvedOperator:
    op_id: str
    op_type: str
    parent_ids: tuple[str, ...]


class OperatorRegistry:
    def __init__(self, bindings: Mapping[str, OperatorBinding]):
        self._by_component_path = dict(bindings)

    @classmethod
    def from_manifest(cls, manifest: IntegrationManifest) -> "OperatorRegistry":
        bindings = [OperatorBinding.from_mapping(item) for item in manifest.operators]
        duplicates = {item.component_path for item in bindings if sum(x.component_path == item.component_path for x in bindings) > 1}
        if duplicates:
            raise ValueError(f"duplicate component paths: {', '.join(sorted(duplicates))}")
        return cls({item.component_path: item for item in bindings})

    @classmethod
    def explicit(
        cls, *, component_path: str, op_id: str, op_type: str, parent_ids: tuple[str, ...] = ()
    ) -> "OperatorRegistry":
        binding = OperatorBinding(component_path, op_id, op_type, parent_ids)
        return cls({component_path: binding})

    def resolve(self, event: ComponentEvent) -> ResolvedOperator:
        binding = self._by_component_path.get(event.path)
        if binding is None:
            raise UnmappedOperatorError(f"unmapped framework component: {event.path}")
        return ResolvedOperator(binding.op_id, binding.op_type, binding.parent_ids)
