from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
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


def _query_with_k(query: Query, k: object) -> Query:
    """The operator's configured ``k`` takes precedence over the incoming ``query.k``."""
    return query if k is None else replace(query, k=int(k))  # type: ignore[call-overload]


def _item_id(item: Any) -> str:
    return str(getattr(item, "candidate_id", None) or getattr(item, "doc_id", None) or getattr(item, "id", item))


class SourceExecutor:
    """Call the bound retriever. ``params["k"]`` (the node's configured k) overrides ``query.k``."""

    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, SourceSpec)
        adapter = context.binding(spec.adapter, "SOURCE")
        fn = getattr(adapter, "retrieve", adapter)
        result = await _call(fn, _query_with_k(context.query, spec.params.get("k")))
        return OperatorExecutionResult(_items(result))


class FuseExecutor:
    """RRF over every parent group, truncated to ``spec.top_k`` (recorded in the span params)."""

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
        ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
        ranked = ordered[: spec.top_k]
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
            ),
            drop_reasons={doc_id: "truncated" for doc_id in ordered[spec.top_k :]},
            metadata={"top_k": spec.top_k},
        )


class RerankExecutor:
    """Call the bound reranker with ``query.k = spec.top_k`` and keep at most ``spec.top_k`` rows.

    The spec's ``top_k`` takes precedence over the incoming ``query.k``. Rows the adapter
    returned beyond ``top_k`` are cut here and recorded as ``drop_reason="truncated"`` so an
    executor-side cut is never mistaken for the reranker scoring them out.
    """

    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        assert isinstance(spec, RerankSpec)
        adapter = context.binding(spec.adapter, "RERANK")
        combined = _combined(input_groups)
        fn = getattr(adapter, "rerank", adapter)
        result = await _call(fn, _query_with_k(context.query, spec.top_k), _documents(combined))
        items = _items(result)
        kept = items[: spec.top_k]
        kept_ids = {_item_id(item) for item in kept}
        drops = {_item_id(item): "truncated" for item in items[spec.top_k :] if _item_id(item) not in kept_ids}
        return OperatorExecutionResult(kept, drop_reasons=drops, metadata={"top_k": spec.top_k})


class NamedExecutor:
    """Call ``binding(query, documents)``. ``params["k"]``, when set, overrides ``query.k``."""

    field_name = ""
    op_type = ""

    async def execute(self, spec: OperatorSpec, input_groups, context: ExecutionContext) -> OperatorExecutionResult:
        name = getattr(spec, self.field_name)
        binding = context.binding(name, self.op_type)
        combined = _combined(input_groups)
        fn = getattr(binding, "execute", binding)
        result = await _call(fn, _query_with_k(context.query, spec.params.get("k")), _documents(combined))
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
