"""Tests for production-tracing convenience + setup-safety fixes."""
import pytest

from retrieval_observatory.tracing import init as tracing_init
from retrieval_observatory.tracing.enrich import detect_suspected_failures
from retrieval_observatory.tracing.recorder import TraceRecorder, _coerce_documents
from retrieval_observatory.tracing.sink import MemorySink
from retrieval_observatory.tracing.types import RetrievalTrace
from retrieval_observatory.types import Document, StageSnapshot

from datetime import datetime, timezone


def _trace(docs):
    return RetrievalTrace(
        trace_id="t", service="s", query_id="q", query_text="hi", pipeline_id="p",
        snapshots=[StageSnapshot(stage_index=0, stage_id="r", documents=docs, latency_ms=1.0)],
        total_latency_ms=1.0, timestamp=datetime.now(timezone.utc), metadata={},
        final_results=docs,
    )


# ---- A2: lazy schema creation -------------------------------------------------
@pytest.mark.asyncio
async def test_store_save_trace_without_init_db(tmp_path):
    """save_trace must auto-create the schema (no manual init_db)."""
    recorder = tracing_init(service="svc", db=str(tmp_path / "prod.db"))
    async with recorder.trace(query_text="hello", pipeline_id="p") as t:
        t.stage("bm25", [Document("d1", "txt", 0.9, 1)], 5.0)
    rows = await recorder.store.list_traces("svc")
    assert len(rows) == 1


# ---- B3: low_confidence no longer fires on zero scores by default -------------
def test_zero_scores_not_low_confidence_by_default():
    labels = detect_suspected_failures(_trace([Document("d1", "txt", 0.0, 1)]))
    assert "low_confidence" not in labels


def test_low_confidence_fires_when_scored_below_floor():
    labels = detect_suspected_failures(
        _trace([Document("d1", "txt", 0.03, 1)]), low_confidence_score=0.05
    )
    assert "low_confidence" in labels


def test_empty_candidates_still_flagged():
    labels = detect_suspected_failures(_trace([]))
    assert "empty_candidates" in labels


# ---- B5: stage context manager ------------------------------------------------
def test_stage_context_manager_times_and_coerces_ids():
    recorder = TraceRecorder(service="s", sink=MemorySink())
    ctx = recorder.start_trace(query_text="q", pipeline_id="p")
    with ctx.stage("bm25", final=True) as s:
        s.results = ["a", "b", "c"]
    snap = ctx.trace.snapshots[0]
    assert snap.stage_id == "bm25"
    assert [d.id for d in snap.documents] == ["a", "b", "c"]
    assert snap.latency_ms >= 0.0
    assert [d.id for d in ctx.trace.final_results] == ["a", "b", "c"]


def test_stage_immediate_form_still_works():
    recorder = TraceRecorder(service="s", sink=MemorySink())
    ctx = recorder.start_trace(query_text="q", pipeline_id="p")
    ctx.stage("bm25", [Document("d1", "txt", 0.9, 1)], 5.0)
    assert ctx.trace.snapshots[0].latency_ms == 5.0


def test_coerce_documents_handles_mixed_inputs():
    docs = _coerce_documents(["a", ("b", 0.5), {"id": "c", "score": 0.3}], corpus={"a": "A"})
    assert [d.id for d in docs] == ["a", "b", "c"]
    assert docs[0].text == "A"
    assert docs[1].score == 0.5


# ---- B1 / B2: middleware path exclusion + query extractor ---------------------
def test_middleware_excludes_infra_paths_and_extracts_q():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from retrieval_observatory.tracing.integrations.fastapi import instrument_fastapi

    sink = MemorySink()
    recorder = TraceRecorder(service="s", sink=sink, sample_rate=1.0)
    app = FastAPI()
    instrument_fastapi(app, recorder)

    @app.get("/search")
    async def search(q: str):
        return {"q": q}

    client = TestClient(app)
    client.get("/openapi.json")  # excluded
    client.get("/search?q=hello+world")  # traced, q extracted
    assert len(sink.traces) == 1
    assert sink.traces[0].query_text == "hello world"
