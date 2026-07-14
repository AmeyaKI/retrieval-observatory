from __future__ import annotations

import asyncio
import time

import pytest

from retrieval_observatory.pipeline.dag import DAGNode, DAGPipeline
from retrieval_observatory.types import Document, Query, RetrievalResult


class _AsyncRetriever:
    def __init__(self, retriever_id: str, *, delay_s: float = 0.0, fail: bool = False):
        self.retriever_id = retriever_id
        self.delay_s = delay_s
        self.fail = fail

    async def retrieve(self, query: Query) -> RetrievalResult:
        started = time.perf_counter()
        await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError(f"{self.retriever_id} failed")
        elapsed_ms = (time.perf_counter() - started) * 1000
        return RetrievalResult(
            documents=[Document(id=self.retriever_id, text="", score=1.0, rank=1)],
            latency_ms=elapsed_ms,
            retriever_id=self.retriever_id,
        )


def _parallel_dag(*, delay_s: float = 0.05) -> DAGPipeline:
    return DAGPipeline(
        pipeline_id="parallel",
        nodes=[
            DAGNode("left", "SOURCE", adapter=_AsyncRetriever("left", delay_s=delay_s)),
            DAGNode("right", "SOURCE", adapter=_AsyncRetriever("right", delay_s=delay_s)),
            DAGNode("fuse", "FUSE", inputs=["left", "right"], top_k=10),
        ],
        output_id="fuse",
    )


@pytest.mark.asyncio
async def test_parallel_sources_overlap_and_record_latency_semantics():
    result = await _parallel_dag().run(Query(query_id="q", text="q", k=10))

    assert result.status == "OK"
    timing = result.trace_v2.timing
    assert timing is not None
    assert timing.operator_sum_ms >= 90
    assert timing.wall_clock_ms < 90
    assert timing.critical_path_ms < 90
    assert result.total_latency_ms == pytest.approx(timing.wall_clock_ms)
    assert result.trace_v2.total_latency_ms == pytest.approx(timing.wall_clock_ms)
    assert [span.op_id for span in result.trace_v2.spans] == ["left", "right", "fuse"]


@pytest.mark.asyncio
async def test_failed_node_returns_partial_error_trace():
    pipeline = DAGPipeline(
        pipeline_id="failure",
        nodes=[
            DAGNode("good", "SOURCE", adapter=_AsyncRetriever("good")),
            DAGNode("bad", "SOURCE", adapter=_AsyncRetriever("bad", fail=True)),
            DAGNode("fuse", "FUSE", inputs=["good", "bad"]),
        ],
        output_id="fuse",
    )

    result = await pipeline.run(Query(query_id="q", text="q", k=10))

    assert result.status == "ERROR"
    assert result.trace_v2 is not None
    assert result.trace_v2.status == "ERROR"
    spans = {span.op_id: span for span in result.trace_v2.spans}
    assert spans["good"].status == "FIRED"
    assert spans["bad"].status == "ERROR"
    assert "bad failed" in (spans["bad"].error or "")
    assert "fuse" not in spans
    assert result.trace_v2.final_op_id == "good"
    assert result.trace_v2.error_traceback


@pytest.mark.asyncio
async def test_cancelled_dag_returns_partial_timeout_trace():
    task = asyncio.create_task(_parallel_dag(delay_s=1.0).run(Query(query_id="q", text="q", k=10)))
    await asyncio.sleep(0.02)
    task.cancel()
    result = await task

    assert result.status == "TIMEOUT"
    assert result.trace_v2 is not None
    assert result.trace_v2.status == "TIMEOUT"
    assert {span.status for span in result.trace_v2.spans} == {"TIMEOUT"}
    assert {span.op_id for span in result.trace_v2.spans} == {"left", "right"}


def test_dag_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(ValueError, match="cycle"):
        DAGPipeline(
            pipeline_id="cycle",
            nodes=[DAGNode("a", "FUSE", inputs=["b"]), DAGNode("b", "FUSE", inputs=["a"])],
            output_id="a",
        )

    with pytest.raises(ValueError, match="unknown input"):
        DAGPipeline(
            pipeline_id="unknown",
            nodes=[DAGNode("a", "FUSE", inputs=["missing"])],
            output_id="a",
        )
