"""List pipelines label their stages with the adapter's operator type; the derived linear trace
uses those labels (and derives candidate ranks) instead of calling every later stage RERANK."""
from __future__ import annotations

from typing import List

import pytest

from retrieval_observatory.adapters.bm25_adapter import BM25Adapter
from retrieval_observatory.adapters.hf_adapter import HFCrossEncoderAdapter
from retrieval_observatory.adapters.rrf_adapter import RRFFusionAdapter
from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.pipeline.single import SingleStagePipeline, stage_op_type
from retrieval_observatory.runner.benchmark import BenchmarkRunner, _linear_trace
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, PipelineResult, Query, RetrievalResult, StageSnapshot

CORPUS = {"d1": "apple pie recipe", "d2": "apple tart", "d3": "banana bread", "d4": "cherry apple"}


class _FuseStage:
    """Stands in for a fusing stage in the middle of a list pipeline."""

    retriever_id = "rrf"
    op_type = "FUSE"

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        return RetrievalResult(documents=list(documents), latency_ms=1.0, retriever_id=self.retriever_id)


class _FakeCrossEncoder(HFCrossEncoderAdapter):
    async def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        ordered = list(reversed(documents))[: query.k]
        docs = [Document(id=d.id, text=d.text, score=1.0, rank=r) for r, d in enumerate(ordered, 1)]
        return RetrievalResult(documents=docs, latency_ms=1.0, retriever_id=self.retriever_id)


class _Plain:
    retriever_id = "plain"

    def retrieve(self, query: Query) -> RetrievalResult:
        return RetrievalResult([Document("d1", "", 1.0, 1)], 1.0, "plain")

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        return RetrievalResult(list(documents), 1.0, "plain")


def test_stage_op_type_rules():
    assert stage_op_type(BM25Adapter(CORPUS), 0) == "SOURCE"
    assert stage_op_type(_FuseStage(), 1) == "FUSE"
    assert stage_op_type(_FakeCrossEncoder(model_name="x"), 2) == "RERANK"
    assert stage_op_type(_Plain(), 0) == "SOURCE"
    assert stage_op_type(_Plain(), 1) == "TRANSFORM"
    # A fusing adapter heading a list pipeline is where candidates enter: the trace's SOURCE.
    assert stage_op_type(RRFFusionAdapter([_Plain(), _Plain()]), 0) == "SOURCE"
    assert stage_op_type(RRFFusionAdapter([_Plain(), _Plain()]), 1) == "FUSE"


@pytest.mark.asyncio
async def test_three_stage_list_pipeline_records_source_fuse_rerank(tmp_path):
    pipeline = MultiStagePipeline(
        pipeline_id="bm25__rrf__rerank",
        stages=[BM25Adapter(CORPUS), _FuseStage(), _FakeCrossEncoder(model_name="ce", retriever_id="ce")],
        k_per_stage=[3, 3, 2],
    )
    store = SQLiteStore(db_path=str(tmp_path / "t.db"))
    await store.init_db()
    await store.save_run("r", "t", "{}")

    results = await BenchmarkRunner(store=store).run([pipeline], [Query("apple", k=3, query_id="q1")], "r")
    assert results["bm25__rrf__rerank"][0].status == "OK"
    assert [s.op_type for s in results["bm25__rrf__rerank"][0].snapshots] == ["SOURCE", "FUSE", "RERANK"]

    trace = (await store.get_traces("r"))[0]
    assert [(s.op_id, s.op_type) for s in trace.spans] == [("bm25", "SOURCE"), ("rrf", "FUSE"), ("ce", "RERANK")]
    assert [s.parent_ids for s in trace.spans] == [(), ("bm25",), ("rrf",)]

    # Ranks: output_rank is the stage rank; input_rank is the rank in the previous stage.
    source_ranks = {c.doc_id: c.rank for c in trace.spans[0].outputs}
    assert all(c.output_rank == c.rank and c.input_rank is None for c in trace.spans[0].outputs)
    for candidate in trace.spans[2].outputs:
        assert candidate.output_rank == candidate.rank
        assert candidate.input_rank == source_ranks[candidate.doc_id]


@pytest.mark.asyncio
async def test_fused_first_stage_is_the_linear_traces_source():
    """An RRF stage 0 (the SDK's [[a, b]] shape) enters the trace as its SOURCE, arms kept as arm snapshots."""
    class _Arm:
        def __init__(self, rid, ids):
            self.retriever_id = rid
            self._ids = ids

        def retrieve(self, query: Query) -> RetrievalResult:
            docs = [Document(i, "", 1.0 / r, r) for r, i in enumerate(self._ids, 1)]
            return RetrievalResult(docs, 1.0, self.retriever_id)

    fused = RRFFusionAdapter([_Arm("lex", ["n1", "n2"]), _Arm("dense", ["rel", "n1"])], retriever_id="fused")
    result = await SingleStagePipeline("hybrid", fused, k=3).run(Query("q", k=3, query_id="q"))
    trace = _linear_trace(result, run_id="r", query_text="q")

    assert result.snapshots[0].op_type == "SOURCE"
    assert [s.stage_id for s in result.snapshots[0].arms] == ["lex", "dense"]
    assert [(s.op_id, s.op_type, s.parent_ids) for s in trace.spans] == [("fused", "SOURCE", ())]
    assert {c.doc_id for c in trace.spans[0].outputs} == {"n1", "n2", "rel"}


def test_linear_trace_falls_back_when_snapshots_carry_no_op_type():
    result = PipelineResult("q", "p", [
        StageSnapshot(0, "first", [Document("d1", "", 1.0, 1)], 1.0),
        StageSnapshot(1, "second", [Document("d1", "", 1.0, 1)], 1.0),
    ], 2.0, "OK")
    trace = _linear_trace(result, run_id="r", query_text="q")
    assert [s.op_type for s in trace.spans] == ["SOURCE", "RERANK"]
