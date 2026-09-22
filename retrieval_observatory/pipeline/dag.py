from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from retrieval_observatory.config.operators import (
    BoostSpec,
    ExpandSpec,
    FuseSpec,
    GenerateSpec,
    PipelineGraphSpec,
    RerankSpec,
    SourceSpec,
    TransformSpec,
)
from retrieval_observatory.pipeline.deadline import cancelled_by_deadline
from retrieval_observatory.pipeline.executors import (
    ExecutionContext,
    OperatorConfigurationError,
    OperatorExecutionResult,
    OperatorExecutor,
    default_operator_executors,
)
from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import (
    OperatorSpan,
    ReplayPolicy,
    RetrievalTrace,
    TraceTiming,
    critical_path_latency_ms,
)
from retrieval_observatory.types import Document, PipelineResult, Query, StageSnapshot

#: Replay tier recorded on every span the DAG produces, keyed by operator type. A SOURCE is
#: promoted to EXACT when a FUSE consumes it (the fusion can be recomputed from the recorded
#: arm outputs without re-running the retriever); a SOURCE nothing fuses stays NOT_REPLAYABLE.
#: An operator spec may override its tier with ``params={"replay_policy": ...}``.
DEFAULT_REPLAY_POLICY: dict[str, ReplayPolicy] = {
    "SOURCE": "NOT_REPLAYABLE",
    "FUSE": "EXACT",
    "FILTER": "EXACT",
    "BOOST": "EXACT",
    "RERANK": "OBSERVED_ABLATION",
    "EXPAND": "OBSERVED_ABLATION",
    "GATE": "OBSERVED_ABLATION",
    "TRANSFORM": "OBSERVED_ABLATION",
    "GENERATE": "NOT_REPLAYABLE",
}
_REPLAY_POLICIES: frozenset[str] = frozenset({"EXACT", "OBSERVED_ABLATION", "NOT_REPLAYABLE"})
_NAMED_LEGACY_SPECS = {
    "BOOST": (BoostSpec, "booster"),
    "EXPAND": (ExpandSpec, "expander"),
    "TRANSFORM": (TransformSpec, "transformer"),
    "GENERATE": (GenerateSpec, "generator"),
}


@dataclass
class DAGNode:
    """Deprecated construction value accepted only at the native Python boundary."""

    node_id: str
    op_type: str
    inputs: list[str] = field(default_factory=list)
    adapter: Any = None
    k: int = 10
    rrf_k: int = 60
    top_k: int = 100
    fetch_k: int = 100


@dataclass(frozen=True)
class _Execution:
    spec: Any
    result: OperatorExecutionResult
    transition: Any
    latency_ms: float
    error: str | None = None
    error_traceback: str | None = None
    # ``invocation_id`` of the span behind each parent group, in ``spec.parents`` order.
    parent_invocation_ids: tuple[str, ...] = ()


def _parent_invocations(spec: Any, invocations: Mapping[str, str]) -> tuple[str, ...]:
    ids = tuple(invocations.get(parent, "") for parent in spec.parents)
    return ids if all(ids) else ()


def _legacy_graph(pipeline_id: str, nodes: Sequence[DAGNode], output_id: str) -> tuple[PipelineGraphSpec, dict[str, Any]]:
    specs = []
    bindings: dict[str, Any] = {}
    for node in nodes:
        parents = tuple(node.inputs)
        if node.op_type == "SOURCE":
            name = f"{node.node_id}:adapter"
            bindings[name] = node.adapter
            specs.append(SourceSpec(node.node_id, parents, {"k": node.k}, adapter=name))
        elif node.op_type == "FUSE":
            specs.append(FuseSpec(node.node_id, parents, {"rrf_k": node.rrf_k}, top_k=node.top_k))
        elif node.op_type == "RERANK":
            name = f"{node.node_id}:adapter"
            bindings[name] = node.adapter
            specs.append(RerankSpec(node.node_id, parents, {"merge_policy": "concat"}, adapter=name, top_k=node.k))
        elif node.op_type in _NAMED_LEGACY_SPECS:
            # A factory-built stage (adapter.import) exposes rerank()/execute() or is itself callable;
            # the named executors call ``binding(query, documents)``.
            cls, field_name = _NAMED_LEGACY_SPECS[node.op_type]
            name = f"{node.node_id}:adapter"
            adapter = node.adapter
            bindings[name] = getattr(adapter, "execute", None) or getattr(adapter, "rerank", None) or adapter
            specs.append(cls(node.node_id, parents, {"k": node.k}, **{field_name: name}))
        else:
            raise OperatorConfigurationError(
                f"Legacy DAGNode cannot express {node.op_type}; use an operator-specific PipelineGraphSpec"
            )
    return PipelineGraphSpec(pipeline_id, tuple(specs), (output_id,)), bindings


class DAGPipeline:
    """Execute validated operator specifications while preserving graph evidence."""

    def __init__(
        self,
        graph: PipelineGraphSpec | None = None,
        adapters: Mapping[str, Any] | None = None,
        executors: Mapping[str, OperatorExecutor] | None = None,
        *,
        pipeline_id: str | None = None,
        nodes: Sequence[DAGNode] | None = None,
        output_id: str | None = None,
        service_id: str = "retobs",
    ):
        if graph is None:
            if pipeline_id is None or nodes is None or output_id is None:
                raise TypeError("DAGPipeline requires graph or pipeline_id/nodes/output_id")
            graph, legacy_adapters = _legacy_graph(pipeline_id, nodes, output_id)
            adapters = {**legacy_adapters, **dict(adapters or {})}
        self.graph = graph
        self.pipeline_id = graph.pipeline_id
        self.service_id = service_id
        self.adapters = dict(adapters or {})
        self.executors = dict(executors or default_operator_executors())
        self.nodes = {item.op_id: item for item in graph.operators}
        self.output_id = graph.final_operator_ids[0] if len(graph.final_operator_ids) == 1 else ""
        self._order = self._topological_order()
        self._order_index = {op_id: index for index, op_id in enumerate(self._order)}
        self._waves = self._execution_waves()
        self._validate_bindings()
        self._replay_policies = {spec.op_id: self._replay_policy_for(spec) for spec in graph.operators}

    def _replay_policy_for(self, spec: Any) -> ReplayPolicy:
        override = spec.params.get("replay_policy")
        if override is not None:
            if str(override) not in _REPLAY_POLICIES:
                raise OperatorConfigurationError(
                    f"{spec.op_id}: replay_policy must be one of {sorted(_REPLAY_POLICIES)}, got {override!r}"
                )
            return str(override)  # type: ignore[return-value]
        if spec.op_type == "SOURCE":
            fused = any(other.op_type == "FUSE" and spec.op_id in other.parents for other in self.graph.operators)
            return "EXACT" if fused else "NOT_REPLAYABLE"
        return DEFAULT_REPLAY_POLICY.get(spec.op_type, "NOT_REPLAYABLE")

    def _deterministic(self, spec: Any) -> bool:
        override = spec.params.get("deterministic")
        if override is not None:
            return bool(override)
        # RRF fusion is a pure function of its recorded inputs; every other operator runs
        # code the trace cannot vouch for (a model, a service, a user callable).
        return spec.op_type == "FUSE"

    def _validate_bindings(self) -> None:
        for spec in self.graph.operators:
            if spec.op_type not in self.executors:
                raise OperatorConfigurationError(f"No {spec.op_type} executor registered for {spec.op_id}")
            field = {
                "SOURCE": "adapter", "RERANK": "adapter", "FILTER": "predicate", "GATE": "router",
                "BOOST": "booster", "EXPAND": "expander", "TRANSFORM": "transformer", "GENERATE": "generator",
            }.get(spec.op_type)
            if field and getattr(spec, field) not in self.adapters:
                raise OperatorConfigurationError(f"No {spec.op_type} executor registered for {spec.op_id}")

    def _topological_order(self) -> list[str]:
        declared = [item.op_id for item in self.graph.operators]
        known = set(declared)
        indegree = {item.op_id: len(item.parents) for item in self.graph.operators}
        children = {op_id: [] for op_id in declared}
        for item in self.graph.operators:
            for parent in item.parents:
                if parent not in known:
                    raise ValueError(f"DAG node '{item.op_id}' has unknown input '{parent}'")
                children[parent].append(item.op_id)
        ready = [op_id for op_id in declared if indegree[op_id] == 0]
        result: list[str] = []
        while ready:
            current = ready.pop(0)
            result.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
            ready.sort(key=declared.index)
        if len(result) != len(declared):
            raise ValueError("DAG contains a cycle")
        return result

    def _execution_waves(self) -> list[list[str]]:
        depth: dict[str, int] = {}
        for op_id in self._order:
            parents = self.nodes[op_id].parents
            depth[op_id] = 0 if not parents else 1 + max(depth[parent] for parent in parents)
        return [[op_id for op_id in self._order if depth[op_id] == value] for value in sorted(set(depth.values()))]

    async def _execute(
        self, spec: Any, query: Query, candidates: Mapping[str, tuple[Any, ...]], parent_invocation_ids: tuple[str, ...] = ()
    ) -> _Execution:
        groups = {parent: candidates.get(parent, ()) for parent in spec.parents}
        started = time.perf_counter()
        try:
            executor = self.executors[spec.op_type]
            result = await executor.execute(spec, groups, ExecutionContext(query, self.adapters))
            result = _drop_duplicate_outputs(result)
            transition = build_candidate_transition(
                input_groups=groups,
                output_items=result.outputs,
                op_id=spec.op_id,
                op_type=spec.op_type,
                decision_reasons=result.drop_reasons,
            )
            return _Execution(spec, result, transition, (time.perf_counter() - started) * 1000, parent_invocation_ids=parent_invocation_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            transition = build_candidate_transition(
                input_groups=groups, output_items=(), op_id=spec.op_id, op_type=spec.op_type
            )
            return _Execution(
                spec, OperatorExecutionResult((), status="ERROR"), transition,
                (time.perf_counter() - started) * 1000, str(exc), traceback.format_exc(), parent_invocation_ids,
            )

    def _span(self, execution: _Execution) -> OperatorSpan:
        """The executor passed each parent's recorded outputs itself, so every link is ``recorded``.
        A gate-skipped operator received nothing; a TIMEOUT/ERROR operator received its inputs
        but produced no observable output."""
        spec, status = execution.spec, "ERROR" if execution.error else execution.result.status
        input_groups = {
            parent: tuple(
                replace(candidate, drop_reason=execution.result.drop_reasons.get(candidate.doc_id, candidate.drop_reason))
                for candidate in candidates
            )
            for parent, candidates in execution.transition.input_groups.items()
        }
        return OperatorSpan(
            op_id=spec.op_id,
            op_type=spec.op_type,
            op_name=spec.op_id,
            parent_ids=tuple(spec.parents),
            status=status,
            latency_ms=max(0.0, execution.latency_ms),
            input_groups=input_groups,
            outputs=execution.transition.outputs,
            deterministic=self._deterministic(spec),
            replay_policy=self._replay_policies[spec.op_id],
            params={**dict(spec.params), **dict(execution.result.metadata)},
            gate_values=dict(execution.result.gate_values),
            error=execution.error,
            branch_id=spec.params.get("branch_id"),
            **self._invocation_links(spec, execution.parent_invocation_ids, received=status != "SKIPPED_BY_GATE"),
            output_capture="recorded" if status == "FIRED" else "unavailable",
        )

    @staticmethod
    def _invocation_links(spec: Any, parent_invocation_ids: tuple[str, ...], *, received: bool) -> dict[str, Any]:
        return {
            "invocation_id": uuid.uuid4().hex,
            "operator_id": spec.op_id,
            "input_capture": "recorded" if spec.parents and received else "not_applicable",
            "parent_invocation_ids": parent_invocation_ids,
            "parent_linkage": "recorded",
        }

    async def run(self, query: Query | str, *, query_id: str | None = None) -> PipelineResult:
        query = Query(str(query), query_id=query_id or "") if isinstance(query, str) else query
        if query_id is not None and query.query_id != query_id:
            query = replace(query, query_id=query_id)
        candidates: dict[str, tuple[Any, ...]] = {}
        invocations: dict[str, str] = {}
        spans: list[OperatorSpan] = []
        snapshots: list[StageSnapshot] = []
        gate_choices: dict[str, tuple[str, tuple[str, ...]]] = {}
        started = time.perf_counter()
        active: list[str] = []

        def result(status: str, error: str | None = None) -> PipelineResult:
            wall = (time.perf_counter() - started) * 1000
            finals = tuple(
                op_id for op_id in self.graph.final_operator_ids
                if any(span.op_id == op_id and span.status == "FIRED" for span in spans)
            ) if status == "OK" else ()
            trace = RetrievalTrace(
                trace_id=uuid.uuid4().hex, service_id=self.service_id, run_id=None,
                query_id=query.query_id, query_text=query.text, pipeline_id=self.pipeline_id,
                spans=tuple(spans), final_op_ids=finals, status=status,
                timing=TraceTiming(wall, critical_path_latency_ms(spans), sum(span.latency_ms for span in spans)),
                metadata=dict(query.metadata), error_traceback=error,
            )
            return PipelineResult(query.query_id, self.pipeline_id, snapshots, wall, status, error, trace=trace)

        try:
            for wave in self._waves:
                active = list(wave)
                pending = []
                for op_id in wave:
                    spec = self.nodes[op_id]
                    skipped_by = next(
                        (
                            (gate_id, route) for gate_id, (route, selected) in gate_choices.items()
                            if op_id in {item for branches in self.nodes[gate_id].branches.values() for item in branches}
                            and op_id not in selected
                        ),
                        None,
                    )
                    if skipped_by:
                        gate_id, route = skipped_by
                        transition = build_candidate_transition(
                            input_groups={}, output_items=(), op_id=op_id, op_type=spec.op_type
                        )
                        pending.append(asyncio.sleep(0, result=_Execution(
                            spec,
                            OperatorExecutionResult(
                                (), status="SKIPPED_BY_GATE",
                                gate_values={"gate_op_id": gate_id, "selected_route": route},
                            ),
                            transition, 0.0, parent_invocation_ids=_parent_invocations(spec, invocations),
                        )))
                    else:
                        pending.append(self._execute(spec, query, candidates, _parent_invocations(spec, invocations)))
                executions = list(await asyncio.gather(*pending))
                active = []
                errors = []
                for execution in executions:
                    try:
                        span = self._span(execution)
                    except ValueError:
                        # The evidence model rejected what the operator produced (lineage it cannot
                        # express). Keep the spans recorded so far and report the failure.
                        errors.append(traceback.format_exc())
                        continue
                    spans.append(span)
                    invocations[span.op_id] = span.invocation_id or ""
                    if execution.error:
                        errors.append(execution.error_traceback or execution.error)
                        continue
                    candidates[execution.spec.op_id] = execution.transition.outputs
                    if execution.spec.op_type == "GATE" and span.status == "FIRED":
                        route = str(span.gate_values["selected_route"])
                        gate_choices[execution.spec.op_id] = (route, tuple(execution.spec.branches[route]))
                    if span.status == "FIRED":
                        docs = [
                            Document(
                                id=item.doc_id, text=str(item.metadata.get("text", "")), score=item.score,
                                rank=item.output_rank or item.rank, metadata=dict(item.metadata),
                            ) for item in span.outputs
                        ]
                        snapshots.append(StageSnapshot(
                            self._order_index[execution.spec.op_id], execution.spec.op_id, docs,
                            execution.latency_ms, candidate_count=len(docs), op_type=execution.spec.op_type,
                        ))
                if errors:
                    return result("ERROR", "\n".join(errors))
            return result("OK")
        except asyncio.CancelledError:
            # Only the runner's own deadline is reported as a TIMEOUT; any other cancellation
            # (shutdown, task-group failure) must keep propagating.
            if not cancelled_by_deadline():
                raise
            elapsed = (time.perf_counter() - started) * 1000
            seen = {span.op_id for span in spans}
            for op_id in active:
                if op_id in seen:
                    continue
                spec = self.nodes[op_id]
                groups = {parent: candidates.get(parent, ()) for parent in spec.parents}
                spans.append(OperatorSpan(
                    op_id, spec.op_type, op_id, tuple(spec.parents), "TIMEOUT", elapsed,
                    input_groups=groups, error="Pipeline execution cancelled or timed out",
                    deterministic=self._deterministic(spec), replay_policy=self._replay_policies[op_id],
                    output_capture="unavailable",
                    **self._invocation_links(spec, _parent_invocations(spec, invocations), received=True),
                ))
            return result("TIMEOUT", "Pipeline execution cancelled or timed out")


def _output_identity(item: Any) -> str:
    """The identity OperatorSpan enforces uniqueness on: candidate_id, else the document id."""
    if isinstance(item, str):
        return item
    for attr in ("candidate_id", "doc_id", "id"):
        value = getattr(item, attr, None)
        if value:
            return str(value)
    metadata = getattr(item, "metadata", None)
    return str(metadata.get("id", "")) if isinstance(metadata, dict) else ""


def _drop_duplicate_outputs(result: OperatorExecutionResult) -> OperatorExecutionResult:
    """Keep the first occurrence of each output identity; record the rest as ``dropped_duplicates``.

    An adapter that returns the same document twice would otherwise make span construction
    raise. The duplicates are recorded in the span params rather than in ``drop_reasons``
    because their surviving twin *is* in the outputs, and a drop reason keyed by that id
    would mislabel the survivor.
    """
    seen: set[str] = set()
    kept: list[Any] = []
    duplicates: list[str] = []
    for item in result.outputs:
        identity = _output_identity(item)
        if identity and identity in seen:
            duplicates.append(identity)
            continue
        if identity:
            seen.add(identity)
        kept.append(item)
    if not duplicates:
        return result
    return replace(result, outputs=tuple(kept), metadata={**dict(result.metadata), "dropped_duplicates": duplicates})


DagPipeline = DAGPipeline
