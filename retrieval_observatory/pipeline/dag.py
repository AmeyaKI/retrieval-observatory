from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List

from retrieval_observatory.tracing.model_v2 import (
    Candidate,
    OperatorSpan,
    RetrievalTraceV2,
    TraceTiming,
    critical_path_latency_ms,
)
from retrieval_observatory.tracing.candidates import build_candidate_transition, clone_candidate, to_candidates
from retrieval_observatory.types import Document, PipelineResult, Query, StageSnapshot


@dataclass
class DAGNode:
    """A resolved DAG node: an adapter (retriever/reranker) or a fusion operator."""
    node_id: str
    op_type: str  # SOURCE | FUSE | RERANK | BOOST | ...
    inputs: List[str] = field(default_factory=list)
    adapter: Any = None  # retriever (source) or reranker (single-input); None for FUSE
    k: int = 10
    rrf_k: int = 60
    top_k: int = 100
    fetch_k: int = 100


@dataclass
class _NodeExecution:
    node_id: str
    docs: List[Document]
    latency_ms: float
    inputs: List[Candidate]
    outputs: List[Candidate]
    error: str | None = None
    error_traceback: str | None = None


def _docs_to_candidates(docs: List[Document], op_id: str) -> List[Candidate]:
    return to_candidates(docs, op_id)


def _rrf_fuse(input_lists: List[List[Document]], rrf_k: int, top_k: int) -> List[Document]:
    """Reciprocal Rank Fusion over already-retrieved ranked lists."""
    fused: Dict[str, float] = {}
    store: Dict[str, Document] = {}
    for docs in input_lists:
        for doc in docs:
            fused[doc.id] = fused.get(doc.id, 0.0) + 1.0 / (rrf_k + doc.rank)
            store.setdefault(doc.id, doc)
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        Document(
            id=doc_id,
            text=store[doc_id].text,
            score=score,
            rank=rank + 1,
            title=store[doc_id].title,
            timestamp=store[doc_id].timestamp,
            metadata=store[doc_id].metadata,
        )
        for rank, (doc_id, score) in enumerate(ranked)
    ]


class DAGPipeline:
    """Executes a directed-acyclic pipeline: parallel source retrievers, fusion merge points,
    and rerank/boost stages, in topological order. Emits a RetrievalTraceV2 whose OperatorSpans
    carry `parent_ids`, so downstream metric bookkeeping (compute_from_traces) and the
    PipelineGraph projection see the true topology instead of a flattened list."""

    def __init__(self, pipeline_id: str, nodes: List[DAGNode], output_id: str):
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("DAG node IDs must be unique")
        if output_id not in set(node_ids):
            raise ValueError(f"DAG output_id '{output_id}' is not a configured node")
        self.pipeline_id = pipeline_id
        self.nodes = {n.node_id: n for n in nodes}
        self.output_id = output_id
        self._order = self._topo_order(nodes)
        self._order_index = {node_id: index for index, node_id in enumerate(self._order)}
        self._waves = self._execution_waves(self._order)

    @staticmethod
    def _topo_order(nodes: List[DAGNode]) -> List[str]:
        node_ids = {node.node_id for node in nodes}
        indeg = {n.node_id: len(n.inputs) for n in nodes}
        adj: Dict[str, List[str]] = {n.node_id: [] for n in nodes}
        for n in nodes:
            for dep in n.inputs:
                if dep not in node_ids:
                    raise ValueError(f"DAG node '{n.node_id}' has unknown input '{dep}'")
                adj[dep].append(n.node_id)
        # Deterministic order: process ready nodes in declaration order.
        decl = [n.node_id for n in nodes]
        ready = [nid for nid in decl if indeg[nid] == 0]
        order: List[str] = []
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for nxt in adj[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt)
            ready.sort(key=decl.index)
        if len(order) != len(nodes):
            raise ValueError("DAG contains a cycle")
        return order

    def _execution_waves(self, order: List[str]) -> List[List[str]]:
        depth_by_id: Dict[str, int] = {}
        for node_id in order:
            parents = self.nodes[node_id].inputs
            depth_by_id[node_id] = 0 if not parents else 1 + max(depth_by_id[parent] for parent in parents)
        waves: Dict[int, List[str]] = {}
        for node_id in order:
            waves.setdefault(depth_by_id[node_id], []).append(node_id)
        return [waves[depth] for depth in sorted(waves)]

    async def _run_adapter_retrieve(self, adapter, query: Query) -> Any:
        if asyncio.iscoroutinefunction(adapter.retrieve):
            return await adapter.retrieve(query)
        return await asyncio.to_thread(adapter.retrieve, query)

    async def _run_adapter_rerank(self, adapter, query: Query, docs: List[Document]) -> Any:
        if asyncio.iscoroutinefunction(adapter.rerank):
            return await adapter.rerank(query, docs)
        return await asyncio.to_thread(adapter.rerank, query, docs)

    async def _execute_node(
        self,
        node_id: str,
        query: Query,
        outputs: Dict[str, List[Document]],
        candidate_outputs: Dict[str, List[Candidate]],
    ) -> _NodeExecution:
        node = self.nodes[node_id]
        node_query = replace(query, k=node.k)
        input_groups = {parent: candidate_outputs.get(parent, []) for parent in node.inputs}
        input_candidates = [clone_candidate(candidate) for candidates in input_groups.values() for candidate in candidates]
        started = time.perf_counter()
        try:
            if node.op_type == "FUSE":
                input_lists = [outputs.get(dep, []) for dep in node.inputs]
                docs = _rrf_fuse(input_lists, node.rrf_k, node.top_k)
                latency_ms = (time.perf_counter() - started) * 1000
            elif not node.inputs:
                result = await self._run_adapter_retrieve(node.adapter, node_query)
                docs = result.documents
                latency_ms = float(result.latency_ms)
            else:
                upstream = outputs.get(node.inputs[0], [])
                result = await self._run_adapter_rerank(node.adapter, node_query, upstream)
                docs = result.documents
                latency_ms = float(result.latency_ms)
            transition_inputs, transition_outputs = build_candidate_transition(
                input_groups=input_groups,
                output_items=docs,
                op_id=node_id,
                op_type=node.op_type,
            )
            return _NodeExecution(
                node_id=node_id,
                docs=docs,
                latency_ms=max(0.0, latency_ms),
                inputs=transition_inputs,
                outputs=transition_outputs,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _NodeExecution(
                node_id=node_id,
                docs=[],
                latency_ms=(time.perf_counter() - started) * 1000,
                inputs=input_candidates,
                outputs=[],
                error=str(exc),
                error_traceback=traceback.format_exc(),
            )

    async def run(self, query: Query) -> PipelineResult:
        outputs: Dict[str, List[Document]] = {}
        candidate_outputs: Dict[str, List[Candidate]] = {}
        spans: List[OperatorSpan] = []
        snapshots: List[StageSnapshot] = []
        pipeline_started = time.perf_counter()
        active_nodes: List[str] = []
        active_started = pipeline_started

        def build_result(status: str, error_traceback: str | None = None) -> PipelineResult:
            wall_clock_ms = (time.perf_counter() - pipeline_started) * 1000
            timing = TraceTiming(
                wall_clock_ms=wall_clock_ms,
                critical_path_ms=critical_path_latency_ms(spans),
                operator_sum_ms=sum(max(0.0, span.latency_ms) for span in spans),
            )
            successful = [span.op_id for span in spans if span.status == "FIRED"]
            final_op_id = self.output_id if status == "OK" else (successful[-1] if successful else None)
            trace = RetrievalTraceV2(
                trace_id="",
                run_id="",
                query_id=query.query_id,
                query_text=query.text,
                pipeline_id=self.pipeline_id,
                spans=spans,
                total_latency_ms=wall_clock_ms,
                timing=timing,
                status=status,  # type: ignore[arg-type]
                final_op_id=final_op_id,
                metadata=dict(query.metadata),
                error_traceback=error_traceback,
            )
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=wall_clock_ms,
                status=status,  # type: ignore[arg-type]
                error_traceback=error_traceback,
                trace_v2=trace,
            )

        try:
            for wave in self._waves:
                active_nodes = list(wave)
                active_started = time.perf_counter()
                executions = await asyncio.gather(
                    *(self._execute_node(node_id, query, outputs, candidate_outputs) for node_id in wave)
                )
                active_nodes = []
                errors: List[str] = []
                for execution in executions:
                    node = self.nodes[execution.node_id]
                    status = "ERROR" if execution.error else "FIRED"
                    spans.append(
                        OperatorSpan(
                            op_id=execution.node_id,
                            op_type=node.op_type,  # type: ignore[arg-type]
                            op_name=execution.node_id,
                            parent_ids=list(node.inputs),
                            status=status,  # type: ignore[arg-type]
                            deterministic=False,
                            replay_policy="NOT_REPLAYABLE",
                            latency_ms=execution.latency_ms,
                            inputs=execution.inputs,
                            outputs=execution.outputs,
                            error=execution.error,
                        )
                    )
                    if execution.error:
                        errors.append(execution.error_traceback or execution.error)
                        continue
                    outputs[execution.node_id] = execution.docs
                    candidate_outputs[execution.node_id] = execution.outputs
                    snapshots.append(
                        StageSnapshot(
                            stage_index=self._order_index[execution.node_id],
                            stage_id=execution.node_id,
                            documents=execution.docs,
                            latency_ms=execution.latency_ms,
                            candidate_count=len(execution.docs),
                            op_type=node.op_type,
                        )
                    )
                if errors:
                    return build_result("ERROR", "\n".join(errors))

            return build_result("OK")
        except asyncio.CancelledError:
            elapsed_ms = (time.perf_counter() - active_started) * 1000
            completed = {span.op_id for span in spans}
            for node_id in active_nodes:
                if node_id in completed:
                    continue
                node = self.nodes[node_id]
                input_candidates = [
                    clone_candidate(candidate)
                    for parent in node.inputs
                    for candidate in candidate_outputs.get(parent, [])
                ]
                spans.append(
                    OperatorSpan(
                        op_id=node_id,
                        op_type=node.op_type,  # type: ignore[arg-type]
                        op_name=node_id,
                        parent_ids=list(node.inputs),
                        status="TIMEOUT",
                        deterministic=False,
                        replay_policy="NOT_REPLAYABLE",
                        latency_ms=elapsed_ms,
                        inputs=input_candidates,
                        error="Pipeline execution cancelled or timed out",
                    )
                )
            return build_result("TIMEOUT", "Pipeline execution cancelled or timed out")
        except Exception:
            return build_result("ERROR", traceback.format_exc())
