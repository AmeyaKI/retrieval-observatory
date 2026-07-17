import asyncio
import random
import time
from dataclasses import dataclass

from retrieval_observatory.tracing.config import OverflowPolicy, TelemetryConfig
from retrieval_observatory.tracing.exporters import TraceExporter
from retrieval_observatory.tracing.health import HealthCounters
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.tracing.serialization import NormalizedTrace, normalize_trace


@dataclass(frozen=True)
class FlushResult:
    timed_out: bool
    unflushed: int


class BufferedTraceSink:
    """A bounded, non-blocking handoff from application code to an exporter."""

    def __init__(
        self,
        exporter: TraceExporter,
        config: TelemetryConfig | None = None,
        *,
        service_id: str = "default",
        redacted_keys: frozenset[str] | None = None,
    ) -> None:
        self.exporter = exporter
        self.config = config or TelemetryConfig()
        self.service_id = service_id
        self.redacted_keys = (
            self.config.redaction.keys if redacted_keys is None else frozenset(key.lower() for key in redacted_keys)
        )
        self.queue: asyncio.Queue[NormalizedTrace] = asyncio.Queue(maxsize=self.config.queue_capacity)
        self.counters = HealthCounters()
        self._worker: asyncio.Task[None] | None = None
        self._accepting = True
        self._in_flight = 0

    async def start(self) -> None:
        if not self._accepting:
            return
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name=f"retobs-telemetry-{self.service_id}")

    def offer(self, trace: RetrievalTrace) -> bool:
        if not self._accepting:
            self.counters.dropped("shutdown")
            return False
        try:
            item = normalize_trace(
                trace,
                limits=self.config.limits,
                redacted_keys=self.redacted_keys,
            )
        except BaseException:
            self.counters.serialization_failed()
            return False
        if item.failed:
            self.counters.serialization_failed()
            return False
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            if self.config.overflow_policy is not OverflowPolicy.DROP_OLDEST:
                self.counters.dropped("queue_full")
                return False
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                self.counters.dropped("queue_full")
                return False
            self.counters.dropped("queue_full_oldest")
            self.queue.put_nowait(item)
        self.counters.accepted()
        self.counters.queue_depth(self.queue.qsize())
        return True

    async def _export(self, batch: list[NormalizedTrace]) -> None:
        for attempt in range(self.config.max_retries + 1):
            try:
                await asyncio.wait_for(
                    self.exporter.export(batch), timeout=self.config.export_timeout_s
                )
                self.counters.exported(len(batch))
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == self.config.max_retries:
                    self.counters.permanent_failed(len(batch))
                    return
                self.counters.retried(len(batch))
                delay = self.config.retry_base_s * (2**attempt)
                if self.config.retry_base_s:
                    delay += random.uniform(0, self.config.retry_base_s)
                await asyncio.sleep(delay)

    async def _run(self) -> None:
        while True:
            first = await self.queue.get()
            batch = [first]
            while len(batch) < self.config.batch_size:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            self._in_flight = len(batch)
            try:
                await self._export(batch)
            finally:
                for _ in batch:
                    self.queue.task_done()
                self._in_flight = 0
                self.counters.queue_depth(self.queue.qsize())

    def _unflushed(self) -> int:
        return self.queue.qsize() + self._in_flight

    async def flush(self, timeout_s: float | None = None) -> FlushResult:
        timeout = self.config.shutdown_timeout_s if timeout_s is None else max(0.0, timeout_s)
        started = time.perf_counter()
        try:
            await asyncio.wait_for(self.queue.join(), timeout)
            result = FlushResult(False, 0)
        except asyncio.TimeoutError:
            result = FlushResult(True, self._unflushed())
        self.counters.flush_latency((time.perf_counter() - started) * 1000)
        return result

    async def shutdown(self, timeout_s: float | None = None) -> FlushResult:
        self._accepting = False
        timeout = self.config.shutdown_timeout_s if timeout_s is None else max(0.0, timeout_s)
        deadline = asyncio.get_running_loop().time() + timeout
        result = await self.flush(timeout)

        worker = self._worker
        if worker is not None and not worker.done():
            worker.cancel()
        if worker is not None:
            try:
                remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                await asyncio.wait_for(worker, remaining)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        if remaining > 0:
            try:
                await asyncio.wait_for(self.exporter.close(), remaining)
            except (Exception, asyncio.CancelledError):
                self.counters.permanent_failed()
        return result

    def health(self):
        return self.counters.snapshot(service_id=self.service_id, sample_rate=self.config.sample_rate)
