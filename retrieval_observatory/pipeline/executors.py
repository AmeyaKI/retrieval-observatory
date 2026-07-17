from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, Sequence

from retrieval_observatory.config.operators import (
    FilterSpec,
    FuseSpec,
    GateSpec,
    OperatorSpec,
    RerankSpec,
    SourceSpec,
)
from retrieval_observatory.tracing.model import Candidate
from retrieval_observatory.types import Document, Query


class OperatorConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionContext:
    query: Query
    adapters: Mapping[str, Any]

    def binding(self, name: str, op_type: str) -> Any:
        binding = self.adapters.get(name)
        if binding is None:
            raise OperatorConfigurationError(f"No {op_type} executor registered for {name}")
        return binding


@dataclass(frozen=True)
class OperatorExecutionResult:
    outputs: tuple[Any, ...]
    status: Literal["FIRED", "SKIPPED_BY_GATE", "ERROR", "TIMEOUT"] = "FIRED"
    gate_values: Mapping[str, object] = field(default_factory=dict)
    drop_reasons: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)


class OperatorExecutor(Protocol):
    async def execute(
        self,
        spec: OperatorSpec,
        input_groups: Mapping[str, tuple[Candidate, ...]],
        context: ExecutionContext,
    ) -> OperatorExecutionResult: ...


def _documents(candidates: Sequence[Candidate]) -> list[Document]:
    return [
        Document(
            id=item.doc_id,
            text=str(item.metadata.get("text", "")),
            score=item.score,
            rank=item.output_rank or item.rank,
            title=str(item.metadata.get("title", "")),
            metadata=dict(item.metadata),
        )
        for item in candidates
    ]


def _items(result: Any) -> tuple[Any, ...]:
    value = getattr(result, "documents", result)
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


async def _call(callable_: Any, *args: Any) -> Any:
    result = callable_(*args)
    return await result if asyncio.iscoroutine(result) else result


def _combined(input_groups: Mapping[str, tuple[Candidate, ...]]) -> tuple[Candidate, ...]:
    return tuple(candidate for candidates in input_groups.values() for candidate in candidates)


class SourceExecutor:
    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, SourceSpec)
        adapter = context.binding(spec.adapter, "SOURCE")
        fn = getattr(adapter, "retrieve", adapter)
        result = await _call(fn, context.query)
        return OperatorExecutionResult(_items(result))


class FuseExecutor:
    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, FuseSpec)
        if spec.method != "rrf":
            raise OperatorConfigurationError(f"Unsupported FUSE method {spec.method!r}")
        rrf_k = int(spec.params.get("rrf_k", 60))
        scores: dict[str, float] = {}
        rows: dict[str, Candidate] = {}
        for candidates in input_groups.values():
            for candidate in candidates:
                rank = candidate.output_rank or candidate.rank
                scores[candidate.doc_id] = scores.get(candidate.doc_id, 0.0) + 1.0 / (rrf_k + rank)
                rows.setdefault(candidate.doc_id, candidate)
        ranked = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))[: spec.top_k]
        return OperatorExecutionResult(
            tuple(
                Document(
                    id=doc_id,
                    text=str(rows[doc_id].metadata.get("text", "")),
                    score=scores[doc_id],
                    rank=index,
                    metadata=dict(rows[doc_id].metadata),
                )
                for index, doc_id in enumerate(ranked, 1)
            )
        )


class RerankExecutor:
    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, RerankSpec)
        adapter = context.binding(spec.adapter, "RERANK")
        combined = _combined(input_groups)
        fn = getattr(adapter, "rerank", adapter)
        result = await _call(fn, context.query, _documents(combined))
        return OperatorExecutionResult(_items(result)[: spec.top_k])


class NamedExecutor:
    field_name = ""
    op_type = ""

    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        name = getattr(spec, self.field_name)
        binding = context.binding(name, self.op_type)
        combined = _combined(input_groups)
        fn = getattr(binding, "execute", binding)
        result = await _call(fn, context.query, _documents(combined))
        return OperatorExecutionResult(_items(result))


class FilterExecutor(NamedExecutor):
    field_name, op_type = "predicate", "FILTER"

    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, FilterSpec)
        binding = context.binding(spec.predicate, "FILTER")
        combined = _combined(input_groups)
        documents = _documents(combined)
        fn = getattr(binding, "filter", binding)
        try:
            result = await _call(fn, context.query, documents)
            kept = _items(result)
        except TypeError:
            kept = tuple(doc for doc in documents if await _call(fn, doc))
        kept_ids = {str(getattr(item, "id", getattr(item, "doc_id", ""))) for item in kept}
        drops = {item.doc_id: "filtered" for item in combined if item.doc_id not in kept_ids}
        return OperatorExecutionResult(kept, drop_reasons=drops)


class GateExecutor(NamedExecutor):
    field_name, op_type = "router", "GATE"

    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, GateSpec)
        router = context.binding(spec.router, "GATE")
        fn = getattr(router, "route", router)
        route = await _call(fn, context.query, _documents(_combined(input_groups)))
        route = str(getattr(route, "route", route))
        if route not in spec.branches:
            raise OperatorConfigurationError(f"GATE {spec.op_id} selected undeclared route {route!r}")
        return OperatorExecutionResult(
            tuple(_documents(_combined(input_groups))),
            gate_values={"selected_route": route, "selected_operator_ids": spec.branches[route]},
        )


class BoostExecutor(NamedExecutor):
    field_name, op_type = "booster", "BOOST"


class ExpandExecutor(NamedExecutor):
    field_name, op_type = "expander", "EXPAND"


class TransformExecutor(NamedExecutor):
    field_name, op_type = "transformer", "TRANSFORM"


class GenerateExecutor(NamedExecutor):
    field_name, op_type = "generator", "GENERATE"


def default_operator_executors() -> dict[str, OperatorExecutor]:
    return {
        "SOURCE": SourceExecutor(),
        "FUSE": FuseExecutor(),
        "RERANK": RerankExecutor(),
        "FILTER": FilterExecutor(),
        "GATE": GateExecutor(),
        "BOOST": BoostExecutor(),
        "EXPAND": ExpandExecutor(),
        "TRANSFORM": TransformExecutor(),
        "GENERATE": GenerateExecutor(),
    }
