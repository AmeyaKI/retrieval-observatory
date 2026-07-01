from retrieval_observatory.tracing.types import RetrievalTrace
from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2
from retrieval_observatory.tracing.recorder import TraceRecorder, TraceRecorderV2, LegacyTraceRecorder
from retrieval_observatory.tracing.sink import StoreSink, HTTPSink, MemorySink, TraceSink
from retrieval_observatory.tracing.enrich import enrich, predict_difficulty, detect_suspected_failures


def init(
    service: str,
    db: str = ".retobs/prod.db",
    *,
    sample_rate: float = 1.0,
    latency_budget_ms: float = 2000.0,
    v2: bool = True,
):
    """One-line production tracing setup.

    Wires a SQLite-backed store + sink into a ready-to-use recorder::

        recorder = retobs.init(service="search-api")
        instrument_fastapi(app, recorder)

    When ``v2=True`` (default), returns a ``TraceRecorderV2`` that emits
    V2 traces (OperatorSpan DAG).  Pass ``v2=False`` for the legacy
    ``TraceRecorder`` that emits V1 ``RetrievalTrace`` objects.
    """
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db)
    sink = StoreSink(store, latency_budget_ms=latency_budget_ms)
    if v2:
        recorder = TraceRecorderV2(service=service, sink=sink, sample_rate=sample_rate)
    else:
        recorder = TraceRecorder(service=service, sink=sink, sample_rate=sample_rate)  # type: ignore[assignment]
    recorder.store = store  # type: ignore[attr-defined]
    return recorder


__all__ = [
    "RetrievalTrace",
    "RetrievalTraceV2",
    "TraceRecorder",
    "TraceRecorderV2",
    "LegacyTraceRecorder",
    "StoreSink",
    "HTTPSink",
    "MemorySink",
    "TraceSink",
    "enrich",
    "predict_difficulty",
    "detect_suspected_failures",
    "init",
]
