from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

PLAN_SCHEMA_VERSION = 2

#: Capabilities verify reports (master plan §3.5). A plan states an expectation for each one.
CAPABILITY_NAMES: tuple[str, ...] = (
    "topology_observed",
    "actual_input_output_capture",
    "candidate_identity",
    "query_identity",
    "final_output_capture",
    "judgment_mapping",
    "declared_route_coverage",
    "cross_run_entity_alignment",
)
CAPABILITY_STATUSES: tuple[str, ...] = ("ready", "partial", "unavailable")
CapabilityStatus = Literal["ready", "partial", "unavailable"]
ActionKind = Literal["install", "source_edit", "benchmark_setup", "scenario_execution"]
#: The only file apply may import a project-authored ``CaptureSpec`` from (never a package).
ADAPTER_MODULE = "retobs_adapter"


class IntegrationPhase(str, Enum):
    PLAN = "plan"
    APPLY = "apply"
    VERIFY = "verify"
    REVERT = "revert"


def _build(cls, value: Mapping[str, Any], **converted: Any):
    """Construct ``cls`` from a mapping: unknown keys are an error, absent optional fields default."""
    known = {item.name for item in fields(cls)}
    unknown = sorted(set(value) - known)
    if unknown:
        raise ValueError(f"{cls.__name__} has no fields {unknown}")
    try:
        return cls(**{**value, **converted})
    except TypeError as error:
        raise ValueError(f"{cls.__name__}: {error}") from error


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
        return _build(cls, value)


@dataclass(frozen=True)
class OperatorMapping:
    op_id: str
    op_type: str
    symbol: str
    relative_path: str
    parent_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    #: How the actual call-boundary inputs are read. ``query:<param>`` for a SOURCE that takes the
    #: query; ``parameters:<a,b>`` when parameters are named after the parents; ``parameter:<name>``
    #: for one candidate-list parameter; ``positional_lanes:<name>`` for one sequence-of-sequences
    #: argument carrying one lane per parent; ``capture`` when ``capture`` names an adapter spec;
    #: ``unavailable`` when nothing above applies (verify then reports missing actual inputs).
    input_mapping: str = "default"
    #: ``return`` (the returned sequence, or its ``.documents``), ``capture``, or ``unavailable``.
    output_mapping: str = "return"
    #: ``retobs_adapter:<symbol>``: a ``CaptureSpec`` defined in the project's root ``retobs_adapter.py``.
    capture: str | None = None
    invocation: Literal["sync", "async"] = "sync"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorMapping":
        return _build(cls, value, parent_ids=tuple(value.get("parent_ids", ())))


@dataclass(frozen=True)
class VerificationScenario:
    scenario_id: str
    query_text: str
    expected_operator_ids: tuple[str, ...]
    expected_edges: tuple[tuple[str, str], ...] = ()
    #: The exact command that executes this scenario against the instrumented project; ``None``
    #: means the agent or user must supply it before the scenario counts as runnable.
    command: str | None = None
    #: The gate route this scenario is declared to exercise (``gate_values["selected_route"]``).
    route: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationScenario":
        return _build(
            cls,
            value,
            expected_operator_ids=tuple(value.get("expected_operator_ids", ())),
            expected_edges=tuple(tuple(edge) for edge in value.get("expected_edges", ())),
        )


@dataclass(frozen=True)
class FinalBoundary:
    """Where the evaluated output leaves the application."""

    kind: Literal["entrypoint_return", "operator_output", "unresolved"] = "unresolved"
    symbol: str | None = None
    relative_path: str | None = None
    op_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FinalBoundary":
        return _build(cls, value)


@dataclass(frozen=True)
class IdentityChoice:
    """How candidates and queries are identified, chosen once per integration."""

    candidate_id_field: str = "id"
    unit: Literal["document", "chunk"] = "document"
    namespace: str = "document"
    corpus_revision: str | None = None
    #: ``argument:<name>`` when the entrypoint receives a query id, else ``hash:query_text``.
    query_id: str = "hash:query_text"
    query_text_parameter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdentityChoice":
        return _build(cls, value)


@dataclass(frozen=True)
class PlannedAction:
    """One thing the integration needs, labelled by who performs it. Apply performs only source edits."""

    kind: ActionKind
    description: str
    command: str | None = None
    performed_by: Literal["apply", "user"] = "user"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannedAction":
        return _build(cls, value)


def _plan_conversions(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "operators": tuple(OperatorMapping.from_dict(item) for item in value.get("operators", ())),
        "candidate_mapping": dict(value.get("candidate_mapping", {})),
        "scenarios": tuple(VerificationScenario.from_dict(item) for item in value.get("scenarios", ())),
        "boundary": FinalBoundary.from_dict(value.get("boundary") or {}),
        "identity": IdentityChoice.from_dict(value.get("identity") or {}),
        "judgments": dict(value.get("judgments") or {}),
        "expected_capabilities": dict(value.get("expected_capabilities") or {}),
    }


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
    #: Blocking: apply refuses while any remain.
    unresolved: tuple[str, ...] = ()
    discovery: Mapping[str, Any] = field(default_factory=dict)
    boundary: FinalBoundary = field(default_factory=FinalBoundary)
    identity: IdentityChoice = field(default_factory=IdentityChoice)
    #: ``{"queries": path|None, "qrels": path|None, "corpus": path|None, "status": "resolved"|"unresolved", "notes": [...]}``
    judgments: Mapping[str, Any] = field(default_factory=dict)
    #: Capability name -> the status this plan expects verify to report.
    expected_capabilities: Mapping[str, str] = field(default_factory=dict)
    actions: tuple[PlannedAction, ...] = ()
    #: Non-blocking questions for the reviewer (unknown output shapes, missing labels, ...).
    open_questions: tuple[str, ...] = ()

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
        discovery: Mapping[str, Any] | None = None,
        boundary: FinalBoundary | None = None,
        identity: IdentityChoice | None = None,
        judgments: Mapping[str, Any] | None = None,
        expected_capabilities: Mapping[str, str] | None = None,
        actions: Sequence[PlannedAction] = (),
        open_questions: Sequence[str] = (),
    ) -> "IntegrationPlan":
        boundary = boundary or FinalBoundary()
        identity = identity or IdentityChoice()
        identity_payload = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "framework": framework,
            "service_id": service_id,
            "pipeline_id": pipeline_id,
            "patches": [asdict(item) for item in patches],
            "operators": [asdict(item) for item in operators],
            "candidate_mapping": dict(candidate_mapping),
            "scenarios": [asdict(item) for item in scenarios],
            "unresolved": list(unresolved),
            "discovery": dict(discovery or {}),
            "boundary": asdict(boundary),
            "identity": asdict(identity),
            "judgments": dict(judgments or {}),
            "expected_capabilities": dict(expected_capabilities or {}),
            "actions": [asdict(item) for item in actions],
            "open_questions": list(open_questions),
        }
        plan_id = sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]
        return cls(
            PLAN_SCHEMA_VERSION,
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
            dict(discovery or {}),
            boundary,
            identity,
            dict(judgments or {}),
            dict(expected_capabilities or {}),
            tuple(actions),
            tuple(open_questions),
        )

    def validate_for_apply(self) -> None:
        if self.unresolved:
            raise ValueError(f"unresolved mappings: {', '.join(self.unresolved)}")
        if not self.candidate_mapping.get("doc_id"):
            raise ValueError("candidate_mapping.doc_id is required")
        low = [item.op_id for item in self.operators if item.confidence < 0.8]
        if low:
            raise ValueError(f"operator confidence below 0.8: {', '.join(low)}")
        bad = [
            item.op_id
            for item in self.operators
            if item.capture is not None
            and not (item.capture.startswith(f"{ADAPTER_MODULE}:") and item.capture.split(":", 1)[1].isidentifier())
        ]
        if bad:
            raise ValueError(f"capture must be '{ADAPTER_MODULE}:<symbol>': {', '.join(bad)}")
        unknown = sorted(set(self.expected_capabilities) - set(CAPABILITY_NAMES))
        if unknown:
            raise ValueError(f"unknown expected capabilities: {', '.join(unknown)}")
        invalid = sorted(name for name, status in self.expected_capabilities.items() if status not in CAPABILITY_STATUSES)
        if invalid:
            raise ValueError(f"expected capability status must be ready|partial|unavailable: {', '.join(invalid)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationPlan":
        return _build(
            cls,
            value,
            patches=tuple(PatchOperation.from_dict(item) for item in value.get("patches", ())),
            unresolved=tuple(value.get("unresolved", ())),
            discovery=dict(value.get("discovery", {})),
            actions=tuple(PlannedAction.from_dict(item) for item in value.get("actions", ())),
            open_questions=tuple(value.get("open_questions", ())),
            **_plan_conversions(value),
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
    reversal_patches: tuple[PatchOperation, ...] = ()
    boundary: FinalBoundary = field(default_factory=FinalBoundary)
    identity: IdentityChoice = field(default_factory=IdentityChoice)
    judgments: Mapping[str, Any] = field(default_factory=dict)
    expected_capabilities: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_plan(
        cls, plan: IntegrationPlan, reversal_patches: Sequence[PatchOperation] = ()
    ) -> "IntegrationManifest":
        return cls(
            PLAN_SCHEMA_VERSION,
            plan.plan_id,
            plan.service_id,
            plan.pipeline_id,
            plan.operators,
            plan.candidate_mapping,
            plan.scenarios,
            tuple(reversal_patches),
            plan.boundary,
            plan.identity,
            dict(plan.judgments),
            dict(plan.expected_capabilities),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationManifest":
        return _build(
            cls,
            value,
            reversal_patches=tuple(PatchOperation.from_dict(item) for item in value.get("reversal_patches", ())),
            **_plan_conversions(value),
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
        return _build(cls, value, limitations=tuple(value.get("limitations", ())))


@dataclass(frozen=True)
class IntegrationResult:
    phase: Literal["plan", "apply", "verify", "revert"]
    status: str
    plan: IntegrationPlan | None = None
    changed_files: tuple[str, ...] = ()
    checks: tuple[IntegrationCheck, ...] = ()
    #: Capability name -> ``{"status": ready|partial|unavailable, "evidence": {...}, "scope": str,
    #: "failures": [{"code", "detail", "fix"}]}`` for every name in ``CAPABILITY_NAMES``.
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    observed_operator_ids: tuple[str, ...] = ()
    topology_variants: tuple[Mapping[str, Any], ...] = ()
    telemetry_health: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    release_readiness: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def normalize(value: Any) -> Any:
            if hasattr(value, "isoformat"):
                return value.isoformat()
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            if isinstance(value, tuple | list):
                return [normalize(item) for item in value]
            return value

        return normalize(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationResult":
        return _build(
            cls,
            value,
            plan=IntegrationPlan.from_dict(value["plan"]) if value.get("plan") else None,
            changed_files=tuple(value.get("changed_files", ())),
            checks=tuple(IntegrationCheck.from_dict(x) for x in value.get("checks", ())),
            capabilities=dict(value.get("capabilities", {})),
            observed_operator_ids=tuple(value.get("observed_operator_ids", ())),
            topology_variants=tuple(dict(x) for x in value.get("topology_variants", ())),
            telemetry_health=dict(value.get("telemetry_health", {})),
            release_readiness=dict(value.get("release_readiness", {})),
            errors=tuple(value.get("errors", ())),
        )


@dataclass(frozen=True)
class IntegrationOptions:
    plan: IntegrationPlan | None = None
    db_path: str = ".retobs/results.db"
    policy_path: str | None = None
    framework: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrationOptions":
        return cls(
            IntegrationPlan.from_dict(value["plan"]) if value.get("plan") else None,
            str(value.get("db_path", ".retobs/results.db")),
            str(value["policy_path"]) if value.get("policy_path") else None,
            str(value["framework"]) if value.get("framework") else None,
        )
