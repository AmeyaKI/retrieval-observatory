from retrieval_observatory.tracing.types import RetrievalTrace
from retrieval_observatory.tracing.recorder import TraceRecorder
from retrieval_observatory.tracing.sink import StoreSink, HTTPSink, MemorySink, TraceSink
from retrieval_observatory.tracing.enrich import enrich, predict_difficulty, detect_suspected_failures


def init(
    service: str,
    db: str = ".retobs/prod.db",
    *,
    sample_rate: float = 1.0,
    latency_budget_ms: float = 2000.0,
):
    """One-line production tracing setup.

    Wires a SQLite-backed store + sink into a ready-to-use TraceRecorder::

        recorder = retobs.init(service="search-api")
        instrument_fastapi(app, recorder)

    The store creates its schema lazily on first write, so no init_db() call is needed.
    The store is attached as ``recorder.store`` for convenience (purge, stats, etc.).
    """
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db)
    sink = StoreSink(store, latency_budget_ms=latency_budget_ms)
    recorder = TraceRecorder(service=service, sink=sink, sample_rate=sample_rate)
    recorder.store = store  # type: ignore[attr-defined]
    return recorder


__all__ = [
    "RetrievalTrace",
    "TraceRecorder",
    "StoreSink",
    "HTTPSink",
    "MemorySink",
    "TraceSink",
    "enrich",
    "predict_difficulty",
    "detect_suspected_failures",
    "init",
]
