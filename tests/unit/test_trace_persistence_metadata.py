"""Traces whose candidate metadata carries application objects (datetime, Path) persist as text."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


async def test_save_trace_serializes_datetime_and_path_metadata(tmp_path: Path) -> None:
    candidate = Candidate(
        "d1", 0.9, 1, origin_op_ids=("source",),
        metadata={"retrieved_at": datetime(2026, 7, 16, tzinfo=timezone.utc), "corpus_path": Path("data/corpus.jsonl")},
    )
    trace = RetrievalTrace(
        "t1", "svc", "run-1", "q1", "query", "pipe",
        (OperatorSpan("source", "SOURCE", "source", (), "FIRED", 1.0, outputs=(candidate,)),), ("source",),
        datetime.now(timezone.utc), timing=TraceTiming(2.0, 1.0, 1.0),
    )
    store = SQLiteStore(db_path=str(tmp_path / "results.db"))
    await store.init_db()

    await store.save_trace(trace)

    loaded = await store.get_trace("t1")
    assert loaded is not None
    metadata = loaded.spans[0].outputs[0].metadata
    assert metadata["retrieved_at"] == "2026-07-16T00:00:00+00:00"
    assert metadata["corpus_path"] == "data/corpus.jsonl"
