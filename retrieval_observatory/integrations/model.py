from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


class IntegrationPhase(str, Enum):
    PLAN = "plan"
    APPLY = "apply"
    VERIFY = "verify"


@dataclass(frozen=True)
class PatchOperation:
    relative_path: str
    precondition_sha256: str
    replacement: str

    @classmethod
    def from_file(cls, root: Path, path: Path, replacement: str) -> "PatchOperation":
        return cls(str(path.resolve().relative_to(root.resolve())), sha256(path.read_bytes()).hexdigest(), replacement)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatchOperation":
        return cls(**value)


@dataclass(frozen=True)
class OperatorMapping:
    op_id: str
    op_type: str
    symbol: str
    relative_path: str
    parent_ids: tuple[str, ...] = ()
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorMapping":
        return cls(**{**value, "parent_ids": tuple(value.get("parent_ids", ()))})


@dataclass(frozen=True)
class VerificationScenario:
    scenario_id: str
    query_text: str
    expected_operator_ids: tuple[str, ...]
    expected_edges: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationScenario":
        return cls(
            **{
                **value,
                "expected_operator_ids": tuple(value.get("expected_operator_ids", ())),
                "expected_edges": tuple(tuple(edge) for edge in value.get("expected_edges", ())),
            }
        )


@dataclass(frozen=True)
class IntegrationPlan:
    schema_version: int
    plan_id: str
    project_root: str
    framework: str
    service_id: str
    pipeline_id: str
    patches: tuple[PatchOperation, ...]
    operators: tuple[OperatorMapping, ...]
    candidate_mapping: Mapping[str, str]
    scenarios: tuple[VerificationScenario, ...]
    unresolved: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        project_root: Path,
        framework: str,
        service_id: str,
        pipeline_id: str,
        patches: Sequence[PatchOperation],
        operators: Sequence[OperatorMapping],
        candidate_mapping: Mapping[str, str],
        scenarios: Sequence[VerificationScenario],
        unresolved: Sequence[str] = (),
    ) -> "IntegrationPlan":
        identity = {
            "schema_version": 1,
            "framework": framework,
            "service_id": service_id,
            "pipeline_id": pipeline_id,
            "patches": [asdict(item) for item in patches],
            "operators": [asdict(item) for item in operators],
            "candidate_mapping": dict(candidate_mapping),
            "scenarios": [asdict(item) for item in scenarios],
            "unresolved": list(unresolved),
        }
        plan_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
        return cls(
            1,
            plan_id,
            str(project_root.resolve()),
            framework,
            service_id,
            pipeline_id,
            tuple(patches),
            tuple(operators),
            dict(candidate_mapping),
            tuple(scenarios),
            tuple(unresolved),
        )

    def validate_for_apply(self) -> None:
        if self.unresolved:
            raise ValueError(f"unresolved mappings: {', '.join(self.unresolved)}")
        if not self.candidate_mapping.get("doc_id"):
            raise ValueError("candidate_mapping.doc_id is required")
        low = [item.op_id for item in self.operators if item.confidence < 0.8]
        if low:
            raise ValueError(f"operator confidence below 0.8: {', '.join(low)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationPlan":
        expected = {field.name for field in __import__("dataclasses").fields(cls)}
        if set(value) != expected:
            raise ValueError(f"IntegrationPlan fields differ: {sorted(set(value) ^ expected)}")
        return cls(
            **{
                **value,
                "patches": tuple(PatchOperation.from_dict(item) for item in value["patches"]),
                "operators": tuple(OperatorMapping.from_dict(item) for item in value["operators"]),
                "candidate_mapping": dict(value["candidate_mapping"]),
                "scenarios": tuple(VerificationScenario.from_dict(item) for item in value["scenarios"]),
                "unresolved": tuple(value.get("unresolved", ())),
            }
        )


@dataclass(frozen=True)
class IntegrationManifest:
    schema_version: int
    plan_id: str
    service_id: str
    pipeline_id: str
    operators: tuple[OperatorMapping, ...]
    candidate_mapping: Mapping[str, str]
    scenarios: tuple[VerificationScenario, ...]

    @classmethod
    def from_plan(cls, plan: IntegrationPlan) -> "IntegrationManifest":
        return cls(
            1, plan.plan_id, plan.service_id, plan.pipeline_id, plan.operators, plan.candidate_mapping, plan.scenarios
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationManifest":
        plan = IntegrationPlan.from_dict(
            {**value, "project_root": "/", "framework": "manifest", "patches": (), "unresolved": ()}
        )
        return cls(
            value["schema_version"],
            value["plan_id"],
            value["service_id"],
            value["pipeline_id"],
            plan.operators,
            plan.candidate_mapping,
            plan.scenarios,
        )


@dataclass(frozen=True)
class IntegrationCheck:
    check_id: str
    status: Literal["ok", "warn", "error", "unavailable"]
    evidence_class: str
    method_version: str
    sample_size: int
    limitations: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    fix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationCheck":
        return cls(**{**value, "limitations": tuple(value.get("limitations", ()))})


@dataclass(frozen=True)
class IntegrationResult:
    phase: Literal["plan", "apply", "verify"]
    status: str
    plan: IntegrationPlan | None = None
    changed_files: tuple[str, ...] = ()
    checks: tuple[IntegrationCheck, ...] = ()
    capabilities: Mapping[str, str] = field(default_factory=dict)
    observed_operator_ids: tuple[str, ...] = ()
    topology_variants: tuple[Mapping[str, Any], ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationResult":
        return cls(
            **{
                **value,
                "plan": IntegrationPlan.from_dict(value["plan"]) if value.get("plan") else None,
                "changed_files": tuple(value.get("changed_files", ())),
                "checks": tuple(IntegrationCheck.from_dict(x) for x in value.get("checks", ())),
                "capabilities": dict(value.get("capabilities", {})),
                "observed_operator_ids": tuple(value.get("observed_operator_ids", ())),
                "topology_variants": tuple(dict(x) for x in value.get("topology_variants", ())),
                "errors": tuple(value.get("errors", ())),
            }
        )


@dataclass(frozen=True)
class IntegrationOptions:
    plan: IntegrationPlan | None = None
    db_path: str = ".retobs/results.db"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationOptions":
        return cls(
            IntegrationPlan.from_dict(value["plan"]) if value.get("plan") else None,
            str(value.get("db_path", ".retobs/results.db")),
        )
