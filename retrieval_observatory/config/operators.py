from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal, Mapping, Union


@dataclass(frozen=True)
class OperatorBase:
    op_id: str
    parents: tuple[str, ...]
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSpec(OperatorBase):
    op_type: Literal["SOURCE"] = "SOURCE"
    adapter: str = ""


@dataclass(frozen=True)
class FuseSpec(OperatorBase):
    op_type: Literal["FUSE"] = "FUSE"
    method: Literal["rrf"] = "rrf"
    top_k: int = 10


@dataclass(frozen=True)
class RerankSpec(OperatorBase):
    op_type: Literal["RERANK"] = "RERANK"
    adapter: str = ""
    top_k: int = 10


@dataclass(frozen=True)
class FilterSpec(OperatorBase):
    op_type: Literal["FILTER"] = "FILTER"
    predicate: str = ""


@dataclass(frozen=True)
class GateSpec(OperatorBase):
    op_type: Literal["GATE"] = "GATE"
    router: str = ""
    branches: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BoostSpec(OperatorBase):
    op_type: Literal["BOOST"] = "BOOST"
    booster: str = ""


@dataclass(frozen=True)
class ExpandSpec(OperatorBase):
    op_type: Literal["EXPAND"] = "EXPAND"
    expander: str = ""


@dataclass(frozen=True)
class TransformSpec(OperatorBase):
    op_type: Literal["TRANSFORM"] = "TRANSFORM"
    transformer: str = ""


@dataclass(frozen=True)
class GenerateSpec(OperatorBase):
    op_type: Literal["GENERATE"] = "GENERATE"
    generator: str = ""


OperatorSpec = Union[
    SourceSpec, FuseSpec, RerankSpec, FilterSpec, GateSpec, BoostSpec, ExpandSpec, TransformSpec, GenerateSpec
]


@dataclass(frozen=True)
class PipelineGraphSpec:
    pipeline_id: str
    operators: tuple[OperatorSpec, ...]
    final_operator_ids: tuple[str, ...]


_TYPES = {
    item.__dataclass_fields__["op_type"].default: item
    for item in (
        SourceSpec,
        FuseSpec,
        RerankSpec,
        FilterSpec,
        GateSpec,
        BoostSpec,
        ExpandSpec,
        TransformSpec,
        GenerateSpec,
    )
}
_EXECUTOR_FIELD = {
    "SOURCE": "adapter",
    "RERANK": "adapter",
    "FILTER": "predicate",
    "GATE": "router",
    "BOOST": "booster",
    "EXPAND": "expander",
    "TRANSFORM": "transformer",
    "GENERATE": "generator",
}


def parse_pipeline_graph(raw: Mapping[str, Any]) -> PipelineGraphSpec:
    operators: list[OperatorSpec] = []
    for item in raw.get("operators", ()):
        op_type = str(item.get("op_type", "")).upper()
        cls = _TYPES.get(op_type)
        if cls is None:
            raise ValueError(f"unknown operator type {op_type!r}")
        accepted = {value.name for value in fields(cls)}
        unknown = set(item) - accepted
        if op_type == "FILTER" and "adapter" in unknown and not item.get("predicate"):
            raise ValueError("FILTER requires a predicate executor")
        if unknown:
            raise ValueError(f"{op_type} received unsupported configuration: {', '.join(sorted(unknown))}")
        values = {
            **item,
            "op_type": op_type,
            "parents": tuple(item.get("parents", ())),
            "params": dict(item.get("params", {})),
        }
        if op_type == "GATE":
            values["branches"] = {key: tuple(value) for key, value in item.get("branches", {}).items()}
        operators.append(cls(**values))
    ids = [item.op_id for item in operators]
    if len(ids) != len(set(ids)):
        raise ValueError("operator IDs must be unique")
    known = set(ids)
    for item in operators:
        unknown = set(item.parents) - known
        if unknown:
            raise ValueError(f"operator {item.op_id} has unknown parents: {', '.join(sorted(unknown))}")
        if item.op_type == "SOURCE" and item.parents:
            raise ValueError("SOURCE cannot have parents")
        if item.op_type == "FUSE" and len(item.parents) < 2:
            raise ValueError("FUSE requires at least two parents")
        if item.op_type not in {"SOURCE", "FUSE"} and len(item.parents) < 1:
            raise ValueError(f"{item.op_type} requires a parent")
        required = _EXECUTOR_FIELD.get(item.op_type)
        if required and not getattr(item, required):
            suffix = "a predicate executor" if item.op_type == "FILTER" else f"{required} executor"
            raise ValueError(f"{item.op_type} requires {suffix}")
    by_id = {item.op_id: item for item in operators}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(op_id: str) -> None:
        if op_id in visiting:
            raise ValueError("operator graph contains a cycle")
        if op_id in visited:
            return
        visiting.add(op_id)
        for parent in by_id[op_id].parents:
            visit(parent)
        visiting.remove(op_id)
        visited.add(op_id)

    for op_id in ids:
        visit(op_id)
    finals = tuple(raw.get("final_operator_ids", ()))
    if not finals:
        raise ValueError("final_operator_ids is required")
    if set(finals) - known:
        raise ValueError("unknown final operator")
    return PipelineGraphSpec(str(raw["pipeline_id"]), tuple(operators), finals)
