from retrieval_observatory.tracing.config import PayloadLimits, RedactionRule, TelemetryConfig
from retrieval_observatory.tracing.exporters import HTTPExporter, MemoryExporter, StoreExporter, TraceExporter
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.tracing.recorder import TraceRecorder
from retrieval_observatory.tracing.sink import BufferedTraceSink
from retrieval_observatory.store.base import InstrumentationHealth


def init(
    service: str,
    db: str = ".retobs/prod.db",
    *,
    sample_rate: float = 1.0,
    config: TelemetryConfig | None = None,
    exporter: TraceExporter | None = None,
) -> TraceRecorder:
    effective = config or TelemetryConfig(sample_rate=sample_rate)
    store = None
    if exporter is None:
        from retrieval_observatory.store.sqlite import SQLiteStore

        store = SQLiteStore(db_path=db)
        exporter = StoreExporter(store)
    sink = BufferedTraceSink(exporter, effective, service_id=service)
    recorder = TraceRecorder(service, sink, effective.sample_rate)
    if store is not None:
        recorder.store = store
    return recorder


__all__ = [
    "BufferedTraceSink",
    "HTTPExporter",
    "InstrumentationHealth",
    "MemoryExporter",
    "PayloadLimits",
    "RedactionRule",
    "RetrievalTrace",
    "StoreExporter",
    "TelemetryConfig",
    "TraceRecorder",
    "init",
]
