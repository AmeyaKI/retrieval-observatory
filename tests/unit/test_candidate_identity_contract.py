from __future__ import annotations

import pytest

from retrieval_observatory.pipeline.dag import DAGNode, DAGPipeline
from retrieval_observatory.tracing.recorder import TraceRecorderV2
from retrieval_observatory.tracing.sink import MemorySink
from retrieval_observatory.types import Document, Query, RetrievalResult


class _Retriever:
    def __init__(self, retriever_id: str, ids: list[str]):
        self.retriever_id = retriever_id
        self.ids = ids

    def retrieve(self, query: Query) -> RetrievalResult:
        return RetrievalResult(
            documents=[Document(id=doc_id, text="", score=1.0 / rank, rank=rank) for rank, doc_id in enumerate(self.ids, 1)],
            latency_ms=1.0,
            retriever_id=self.retriever_id,
        )


class _Reranker:
    retriever_id = "rerank"

    def rerank(self, query: Query, documents: list[Document]) -> RetrievalResult:
        kept = [doc for doc in documents if doc.id != "left-only"]
        reranked = [
            Document(id=doc.id, text=doc.text, score=10.0 - rank, rank=rank, metadata=doc.metadata)
            for rank, doc in enumerate(reversed(kept), 1)
        ]
        return RetrievalResult(documents=reranked, latency_ms=1.0, retriever_id=self.retriever_id)


@pytest.mark.asyncio
async def test_origins_and_rank_transitions_survive_fusion_and_rerank():
    pipeline = DAGPipeline(
        pipeline_id="hybrid",
        nodes=[
            DAGNode("left", "SOURCE", adapter=_Retriever("left", ["shared", "left-only"])),
            DAGNode("right", "SOURCE", adapter=_Retriever("right", ["right-only", "shared"])),
            DAGNode("fuse", "FUSE", inputs=["left", "right"], top_k=10),
            DAGNode("rerank", "RERANK", inputs=["fuse"], adapter=_Reranker()),
        ],
        output_id="rerank",
    )

    trace = (await pipeline.run(Query(query_id="q", text="q"))).trace_v2
    spans = {span.op_id: span for span in trace.spans}

    shared_fused = next(candidate for candidate in spans["fuse"].outputs if candidate.doc_id == "shared")
    assert shared_fused.origin_op_ids == ["left", "right"]
    assert shared_fused.score_components == {"left": 1.0, "right": 0.5}
    assert shared_fused.add_reason == "fused"
    assert shared_fused.output_rank == shared_fused.rank

    shared_reranked = next(candidate for candidate in spans["rerank"].outputs if candidate.doc_id == "shared")
    assert shared_reranked.origin_op_ids == ["left", "right"]
    assert shared_reranked.input_rank == shared_fused.rank
    assert shared_reranked.output_rank == shared_reranked.rank

    dropped = next(candidate for candidate in spans["rerank"].inputs if candidate.doc_id == "left-only")
    assert dropped.input_rank is not None
    assert dropped.output_rank is None
    assert dropped.drop_reason == "reranked_out"


@pytest.mark.asyncio
async def test_final_trace_candidates_match_pipeline_output():
    pipeline = DAGPipeline(
        pipeline_id="linear",
        nodes=[
            DAGNode("source", "SOURCE", adapter=_Retriever("source", ["a", "b"])),
            DAGNode("rerank", "RERANK", inputs=["source"], adapter=_Reranker()),
        ],
        output_id="rerank",
    )
    result = await pipeline.run(Query(query_id="q", text="q"))

    final_docs = [doc.id for doc in result.snapshots[-1].documents]
    final_candidates = [candidate.doc_id for candidate in result.trace_v2.spans[-1].outputs]
    assert final_candidates == final_docs


def test_v2_recorder_span_preserves_parent_origins_and_inputs():
    recorder = TraceRecorderV2(service="svc", sink=MemorySink())
    ctx = recorder.start_trace(query_text="q", pipeline_id="p", query_id="q")
    source = ctx.span(
        "SOURCE",
        "source",
        [Document(id="d1", text="", score=0.5, rank=1)],
        1.0,
        op_id="source",
    )
    rerank = ctx.span(
        "RERANK",
        "rerank",
        [Document(id="d1", text="", score=0.9, rank=1)],
        1.0,
        op_id="rerank",
    )

    assert source is not None and rerank is not None
    assert [candidate.doc_id for candidate in rerank.inputs] == ["d1"]
    assert rerank.outputs[0].origin_op_ids == ["source"]
    assert rerank.outputs[0].input_rank == 1
