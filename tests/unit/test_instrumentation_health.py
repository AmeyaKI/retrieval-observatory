from datetime import datetime, timezone

import pytest

from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.config import TelemetryConfig
from retrieval_observatory.tracing.health import HealthCounters


def test_telemetry_config_is_bounded() -> None:
    with pytest.raises(ValueError, match="queue_capacity must be positive"):
        TelemetryConfig(queue_capacity=0)
    with pytest.raises(ValueError, match="shutdown_timeout_s"):
        TelemetryConfig(shutdown_timeout_s=-1)


def test_health_snapshot_is_consistent() -> None:
    counters = HealthCounters()
    counters.accepted(3)
    counters.dropped("queue_full", 2)
    counters.exported()
    snapshot = counters.snapshot(service_id="svc")
    assert snapshot.accepted == 3 and snapshot.dropped == 2 and snapshot.drop_reasons == {"queue_full": 2}


@pytest.mark.asyncio
async def test_health_snapshot_round_trips_last_export_time(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "health.db"))
    counters = HealthCounters()
    counters.exported()
    counters.flush_latency(2.5)
    snapshot = counters.snapshot(service_id="svc", sample_rate=0.5)
    await store.save_instrumentation_health(snapshot)
    restored = await store.get_instrumentation_health("svc")
    assert restored is not None
    assert isinstance(restored.last_export_at, datetime)
    assert restored.last_export_at.tzinfo == timezone.utc
    assert restored.last_flush_latency_ms == 2.5
