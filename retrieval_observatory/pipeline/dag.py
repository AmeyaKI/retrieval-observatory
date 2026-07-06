from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
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


def _docs_to_candidates(docs: List[Document], op_id: str) -> List[Candidate]:
    return [
        Candidate(doc_id=str(d.id), score=float(d.score), rank=int(d.rank), origin_op_ids=[op_id])
        for d in docs
    ]


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
        self.pipeline_id = pipeline_id
        self.nodes = {n.node_id: n for n in nodes}
        self.output_id = output_id
        self._order = self._topo_order(nodes)

    @staticmethod
    def _topo_order(nodes: List[DAGNode]) -> List[str]:
        indeg = {n.node_id: len(n.inputs) for n in nodes}
        adj: Dict[str, List[str]] = {n.node_id: [] for n in nodes}
        for n in nodes:
            for dep in n.inputs:
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
        return order

    async def _run_adapter_retrieve(self, adapter, query: Query) -> Any:
        if asyncio.iscoroutinefunction(adapter.retrieve):
            return await adapter.retrieve(query)
        return await asyncio.to_thread(adapter.retrieve, query)

    async def _run_adapter_rerank(self, adapter, query: Query, docs: List[Document]) -> Any:
        if asyncio.iscoroutinefunction(adapter.rerank):
            return await adapter.rerank(query, docs)
        return await asyncio.to_thread(adapter.rerank, query, docs)

    async def run(self, query: Query) -> PipelineResult:
        outputs: Dict[str, List[Document]] = {}
        spans: List[OperatorSpan] = []
        snapshots: List[StageSnapshot] = []
        total_latency = 0.0

        try:
            for depth_index, node_id in enumerate(self._order):
                node = self.nodes[node_id]
                node_query = replace(query, k=node.k)
                start = time.perf_counter()

                if node.op_type == "FUSE":
                    input_lists = [outputs.get(dep, []) for dep in node.inputs]
                    docs = _rrf_fuse(input_lists, node.rrf_k, node.top_k)
                    latency_ms = (time.perf_counter() - start) * 1000
                elif not node.inputs:
                    result = await self._run_adapter_retrieve(node.adapter, node_query)
                    docs = result.documents
                    latency_ms = result.latency_ms
                else:
                    upstream = outputs.get(node.inputs[0], [])
                    result = await self._run_adapter_rerank(node.adapter, node_query, upstream)
                    docs = result.documents
                    latency_ms = result.latency_ms

                outputs[node_id] = docs
                total_latency += latency_ms
                spans.append(
                    OperatorSpan(
                        op_id=node_id,
                        op_type=node.op_type,  # type: ignore[arg-type]
                        op_name=node_id,
                        parent_ids=list(node.inputs),
                        status="FIRED",
                        deterministic=False,
                        replay_policy="NOT_REPLAYABLE",
                        latency_ms=latency_ms,
                        outputs=_docs_to_candidates(docs, node_id),
                    )
                )
                snapshots.append(
                    StageSnapshot(
                        stage_index=depth_index,
                        stage_id=node_id,
                        documents=docs,
                        latency_ms=latency_ms,
                        candidate_count=len(docs),
                        op_type=node.op_type,
                    )
                )

            trace = RetrievalTraceV2(
                trace_id="",  # filled by the runner with run scoping
                run_id="",
                query_id=query.query_id,
                query_text=query.text,
                pipeline_id=self.pipeline_id,
                spans=spans,
                total_latency_ms=total_latency,
                status="OK",
                final_op_id=self.output_id,
                metadata=dict(query.metadata),
            )
            result = PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=total_latency,
                status="OK",
            )
            result.trace_v2 = trace  # type: ignore[attr-defined]
            return result
        except asyncio.CancelledError:
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=total_latency,
                status="TIMEOUT",
            )
        except Exception:
            return PipelineResult(
                query_id=query.query_id,
                pipeline_id=self.pipeline_id,
                snapshots=snapshots,
                total_latency_ms=total_latency,
                status="ERROR",
                error_traceback=traceback.format_exc(),
            )
