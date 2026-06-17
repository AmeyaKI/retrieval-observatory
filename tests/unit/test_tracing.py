import os
import tempfile

import pytest

from retrieval_observatory.types import Document
from retrieval_observatory.tracing import TraceRecorder, MemorySink, enrich, predict_difficulty
from retrieval_observatory.tracing.types import RetrievalTrace
from retrieval_observatory.tracing.enrich import detect_suspected_failures
from retrieval_observatory.tracing.monitor.distribution import summarize, compute_distribution
from retrieval_observatory.store.sqlite import SQLiteStore


def _docs(n, score=0.8):
    return [Document(id=f"d{i}", text="x", score=score, rank=i + 1) for i in range(n)]


def _trace(query="hello world", snaps=None, final=None, latency=50.0, status="OK"):
    from retrieval_observatory.types import StageSnapshot
    snapshots = []
    for i, docs in enumerate(snaps or []):
        snapshots.append(StageSnapshot(stage_index=i, stage_id=f"s{i}", documents=docs,
                                       latency_ms=10.0, candidate_count=len(docs)))
    return RetrievalTrace(
        trace_id="t1", service="svc", query_id="q1", query_text=query,
        pipeline_id="p", snapshots=snapshots, total_latency_ms=latency,
        status=status, final_results=final if final is not None else (snapshots[-1].documents if snapshots else []),
    )


def test_predict_difficulty_monotonic():
    assert predict_difficulty("password reset") == "easy"
    hard = predict_difficulty("compare the 2022 and 2024 policy versus the older one, excluding refunds")
    assert hard in ("hard", "extreme")


def test_proxy_empty_candidates():
    t = _trace(snaps=[[]], final=[])
    assert "empty_candidates" in detect_suspected_failures(t)


def test_proxy_latency_over_budget():
    t = _trace(snaps=[_docs(5)], latency=5000.0)
    assert "latency_over_budget" in detect_suspected_failures(t, latency_budget_ms=2000.0)


def test_proxy_high_churn():
    # stage 0 has 10 docs, stage 1 keeps only 1 → churn 0.9
    t = _trace(snaps=[_docs(10), _docs(1)])
    assert "high_churn" in detect_suspected_failures(t)


def test_enrich_populates_fields():
    t = _trace(snaps=[_docs(5)])
    enrich(t)
    assert t.predicted_difficulty is not None
    assert isinstance(t.suspected_failures, list)


@pytest.mark.asyncio
async def test_recorder_records_and_preserves_partial_on_error():
    sink = MemorySink()
    rec = TraceRecorder(service="svc", sink=sink)
    with pytest.raises(RuntimeError):
        async with rec.trace(query_text="q", pipeline_id="p") as t:
            t.stage("bm25", _docs(3), 12.0)
            raise RuntimeError("boom")
    assert len(sink.traces) == 1
    rt = sink.traces[0]
    assert rt.status == "ERROR"
    assert len(rt.snapshots) == 1  # partial stage preserved
    assert rt.error_traceback is not None


@pytest.mark.asyncio
async def test_recorder_sample_rate_zero_is_noop():
    sink = MemorySink()
    rec = TraceRecorder(service="svc", sink=sink, sample_rate=0.0)
    async with rec.trace(query_text="q", pipeline_id="p") as t:
        t.stage("bm25", _docs(3), 12.0)
        t.set_results(_docs(3))
    assert len(sink.traces) == 0


@pytest.mark.asyncio
async def test_store_save_list_get_purge():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "t.db"))
    await store.init_db()
    t = _trace(snaps=[_docs(4), _docs(2)])
    enrich(t)
    await store.save_trace(t)

    services = await store.list_services()
    assert services and services[0]["service"] == "svc" and services[0]["trace_count"] == 1

    rows = await store.list_traces("svc")
    assert len(rows) == 1 and rows[0]["trace_id"] == "t1"

    full = await store.get_trace("t1")
    assert full and len(full["stages"]) == 2

    deleted = await store.purge_traces(service="svc")
    assert deleted == 1
    assert await store.list_traces("svc") == []


@pytest.mark.asyncio
async def test_summarize_and_distribution():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "t.db"))
    await store.init_db()
    # 1 empty-candidate failure + 1 healthy
    bad = _trace(snaps=[[]], final=[]); bad.trace_id = "bad"; bad.query_id = "qb"
    good = _trace(snaps=[_docs(5)]); good.trace_id = "good"; good.query_id = "qg"
    for t in (bad, good):
        enrich(t)
        await store.save_trace(t)
    rows = await store.list_traces("svc")
    s = summarize(rows)
    assert s["trace_count"] == 2
    assert s["suspected_failure_rate"] == 0.5
    dist = compute_distribution(rows)
    assert dist["by_failure_label"].get("empty_candidates") == 1
