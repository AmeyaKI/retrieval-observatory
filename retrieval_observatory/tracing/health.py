from collections import Counter
from datetime import datetime, timezone
from threading import Lock

from retrieval_observatory.store.base import InstrumentationHealth


class HealthCounters:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()
        self._drops: Counter[str] = Counter()
        self._high_water = 0
        self._last_export_at: datetime | None = None
        self._last_flush_latency_ms: float | None = None

    def accepted(self, count: int = 1) -> None:
        self._add("accepted", count)

    def exported(self, count: int = 1) -> None:
        with self._lock:
            self._counts["exported"] += count
            self._last_export_at = datetime.now(timezone.utc)

    def flush_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._last_flush_latency_ms = max(0.0, latency_ms)

    def serialization_failed(self, count: int = 1) -> None:
        self._add("serialization_failures", count)

    def retried(self, count: int = 1) -> None:
        self._add("retries", count)

    def permanent_failed(self, count: int = 1) -> None:
        self._add("permanent_failures", count)

    def sampled_out(self, count: int = 1) -> None:
        self._add("sampled_out", count)

    def _add(self, key: str, count: int) -> None:
        with self._lock:
            self._counts[key] += count

    def dropped(self, reason: str, count: int = 1) -> None:
        with self._lock:
            self._counts["dropped"] += count
            self._drops[reason] += count

    def queue_depth(self, depth: int) -> None:
        with self._lock:
            self._counts["queue_depth"] = depth
            self._high_water = max(self._high_water, depth)

    def snapshot(self, *, service_id: str, sample_rate: float = 1.0) -> InstrumentationHealth:
        with self._lock:
            return InstrumentationHealth(
                service_id=service_id,
                accepted=self._counts["accepted"],
                exported=self._counts["exported"],
                dropped=self._counts["dropped"],
                serialization_failures=self._counts["serialization_failures"],
                retries=self._counts["retries"],
                permanent_failures=self._counts["permanent_failures"],
                queue_depth=self._counts["queue_depth"],
                queue_high_water=self._high_water,
                drop_reasons=dict(self._drops),
                sample_rate=sample_rate,
                observed_at=datetime.now(timezone.utc),
                last_export_at=self._last_export_at,
                last_flush_latency_ms=self._last_flush_latency_ms,
            )
