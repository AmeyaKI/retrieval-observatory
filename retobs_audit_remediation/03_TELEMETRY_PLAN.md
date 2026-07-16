# Non-blocking Safe Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure trace capture is bounded, asynchronous, privacy-aware, observable, and incapable of changing retrieval request success or latency beyond bounded in-memory work.

**Architecture:** A recorder builds trace state in memory and offers an immutable normalized envelope to a bounded queue on completion. One background worker batches to a reusable exporter with finite retry and explicit overflow/shutdown behavior; every loss or limitation is counted and persisted as instrumentation health.

**Tech Stack:** Python 3.10+, asyncio, dataclasses, aiosqlite, httpx, FastAPI lifespan, pytest, pytest-asyncio

## Global Constraints

- **One public integration workflow:** `retobs integrate <project>` and MCP `integrate_project` expose `plan`, `apply`, and `verify` phases with equivalent contracts.
- **V2 only:** remove V1 trace models, V1 persistence, V1 production readers, legacy recorders, dual-path adapters, and compatibility aliases.
- **No deprecated vocabulary:** remove `wire`, `bootstrap_project`, `TraceLens`, `Forge`, `Advisor`, and `Benchmarks` as public commands, tools, routes, or peer-product names. Internal modules may be renamed when touched; no public documentation may teach the old terms.
- **Observed truth over inference:** integration verification proves stable identity, topology, candidate transitions, timing, and coverage from representative traces. File presence is not readiness.
- **Application wins over telemetry:** instrumentation cannot fail a retrieval request, block indefinitely, or grow memory without bounds.
- **One identity model:** evaluation and production share service, run, trace, query, pipeline, operator, candidate, corpus, dataset, and index-version semantics.
- **Evidence is typed:** every metric, diagnosis, recommendation, alert, and chart states its evidence class, method/version, sample, thresholds, limitations, and unavailable reason.
- **Clean break:** current beta databases may be reset or explicitly upgraded once. No indefinite dual-read or deprecated-command migration layer will be built.
- **Local-first safety:** dashboard servers bind to `127.0.0.1` by default; remote exposure requires explicit configuration.
- **No feature is complete without installed-package and live-product proof.**

---

## File structure

- `tracing/config.py`: queue, retry, limits, redaction, and sampling configuration.
- `tracing/serialization.py`: normalization, redaction, and payload budgets.
- `tracing/health.py`: lock-safe counters and snapshots.
- `tracing/exporters.py`: SQLite, HTTP, and memory batch exporters.
- `tracing/sink.py`: bounded queue worker and lifecycle.
- `tracing/recorder.py`: sole non-blocking recorder.
- `tracing/integrations/fastapi.py`: trace scope plus lifespan shutdown.
- `dashboard/api.py`: instrumentation health endpoint.

### Task 1: Define telemetry policy and health contracts

**Files:**
- Create: `retrieval_observatory/tracing/config.py`
- Create: `retrieval_observatory/tracing/health.py`
- Test: `tests/unit/test_instrumentation_health.py`

**Interfaces:**
- Consumes: none.
- Produces: `OverflowPolicy`, `TelemetryConfig`, `PayloadLimits`, `RedactionRule`, `InstrumentationHealth`, `HealthCounters`.

- [ ] **Step 1: Write failing validation and counter tests**

```python
def test_telemetry_config_is_bounded():
    with pytest.raises(ValueError, match="queue_capacity must be positive"):
        TelemetryConfig(queue_capacity=0)
    with pytest.raises(ValueError, match="shutdown_timeout_s"):
        TelemetryConfig(shutdown_timeout_s=-1)

def test_health_counters_snapshot_is_consistent():
    counters = HealthCounters()
    counters.accepted(3); counters.dropped("queue_full", 2); counters.exported(1)
    snapshot = counters.snapshot(service_id="svc")
    assert snapshot.accepted == 3
    assert snapshot.dropped == 2
    assert snapshot.drop_reasons == {"queue_full": 2}
    assert snapshot.exported == 1
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_instrumentation_health.py`

Expected: collection fails because `tracing.config` and `tracing.health` are absent.

- [ ] **Step 3: Implement exact defaults and counters**

```python
class OverflowPolicy(str, Enum):
    DROP_NEWEST = "drop_newest"
    DROP_OLDEST = "drop_oldest"

@dataclass(frozen=True)
class PayloadLimits:
    max_payload_bytes: int = 1_000_000
    max_candidates_per_span: int = 200
    max_string_chars: int = 8_192
    max_collection_items: int = 500
    max_depth: int = 8

@dataclass(frozen=True)
class TelemetryConfig:
    queue_capacity: int = 1_000
    batch_size: int = 50
    flush_interval_s: float = 1.0
    shutdown_timeout_s: float = 5.0
    export_timeout_s: float = 3.0
    max_retries: int = 2
    retry_base_s: float = 0.1
    overflow_policy: OverflowPolicy = OverflowPolicy.DROP_NEWEST
    sample_rate: float = 1.0
    limits: PayloadLimits = field(default_factory=PayloadLimits)

    def __post_init__(self):
        if self.queue_capacity <= 0: raise ValueError("queue_capacity must be positive")
        if self.batch_size <= 0 or self.batch_size > self.queue_capacity: raise ValueError("batch_size must be within queue capacity")
        if self.shutdown_timeout_s < 0: raise ValueError("shutdown_timeout_s must be non-negative")
        if not 0 <= self.sample_rate <= 1: raise ValueError("sample_rate must be between 0 and 1")
```

`HealthCounters` uses `threading.Lock`, stores accepted/exported/dropped/serialization failures/retries/permanent failures/current and high-water queue depth/last export and flush latency, and returns an immutable `InstrumentationHealth` snapshot.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_instrumentation_health.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/tracing/config.py retrieval_observatory/tracing/health.py tests/unit/test_instrumentation_health.py
git commit -m "feat(telemetry): define bounded policy and health counters"
```

### Task 2: Normalize, redact, and size-limit before enqueue

**Files:**
- Create: `retrieval_observatory/tracing/serialization.py`
- Test: `tests/unit/test_trace_serialization.py`
- Test: `tests/unit/test_trace_redaction.py`

**Interfaces:**
- Consumes: `RetrievalTrace` from `02_TRACE_STORAGE_PLAN.md`, `PayloadLimits`.
- Produces: `normalize_trace(trace, *, limits, redacted_keys) -> NormalizedTrace`; `NormalizationReport`.

- [ ] **Step 1: Write failing non-JSON and secret-redaction tests**

```python
def test_normalize_handles_non_json_metadata(trace_factory):
    trace = trace_factory(metadata={"when": datetime(2026, 1, 1, tzinfo=timezone.utc),
                                    "ids": {UUID(int=1)}, "blob": b"abc"})
    normalized = normalize_trace(trace, limits=PayloadLimits(), redacted_keys=frozenset())
    json.dumps(normalized.payload)
    assert normalized.payload["metadata"]["blob"] == "<bytes:3>"

def test_redacts_nested_secrets_and_truncates_candidates(trace_factory):
    trace = trace_factory(metadata={"authorization": "Bearer secret", "nested": {"api_key": "x"}}, candidate_count=5)
    normalized = normalize_trace(trace, limits=PayloadLimits(max_candidates_per_span=2),
                                 redacted_keys=frozenset({"authorization", "api_key"}))
    assert normalized.payload["metadata"]["authorization"] == "[REDACTED]"
    assert normalized.report.redacted_fields == 2
    assert normalized.report.omitted_candidates == 3
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_trace_serialization.py tests/unit/test_trace_redaction.py`

Expected: collection fails because `tracing.serialization` is absent.

- [ ] **Step 3: Implement deterministic normalization**

```python
def normalize_value(value, *, key, depth, limits, redacted_keys, report):
    if key.lower() in redacted_keys:
        report.redacted_fields += 1
        return "[REDACTED]"
    if depth > limits.max_depth:
        report.omitted_fields += 1
        return "[OMITTED:MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)): return value
    if isinstance(value, str): return value[:limits.max_string_chars]
    if isinstance(value, bytes): return f"<bytes:{len(value)}>"
    if isinstance(value, (datetime, UUID, Enum, Path)): return str(value.value if isinstance(value, Enum) else value)
    if is_dataclass(value): return normalize_value(asdict(value), key=key, depth=depth+1, limits=limits, redacted_keys=redacted_keys, report=report)
    if isinstance(value, dict):
        return {str(k): normalize_value(v, key=str(k), depth=depth+1, limits=limits,
                redacted_keys=redacted_keys, report=report) for k, v in list(value.items())[:limits.max_collection_items]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [normalize_value(v, key=key, depth=depth+1, limits=limits,
                redacted_keys=redacted_keys, report=report) for v in list(value)[:limits.max_collection_items]]
    report.omitted_fields += 1
    return f"<unsupported:{type(value).__name__}>"
```

After candidate truncation, serialize canonical JSON and, if above `max_payload_bytes`, remove candidate metadata then candidate text, recording each omission. If still oversized, return a normalization failure rather than enqueueing a partial invalid trace.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_trace_serialization.py tests/unit/test_trace_redaction.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/tracing/serialization.py tests/unit/test_trace_serialization.py tests/unit/test_trace_redaction.py
git commit -m "feat(telemetry): normalize and redact trace payloads"
```

### Task 3: Implement reusable batch exporters

**Files:**
- Create: `retrieval_observatory/tracing/exporters.py`
- Test: `tests/unit/test_trace_exporters.py`

**Interfaces:**
- Consumes: `NormalizedTrace`, unified `BaseStore.save_traces()`.
- Produces: `TraceExporter.export(batch)`, `close()`; `StoreExporter`, `HTTPExporter`, `MemoryExporter`.

- [ ] **Step 1: Write failing batch and HTTP client reuse tests**

```python
@pytest.mark.asyncio
async def test_store_exporter_writes_one_batch(store, normalized_batch):
    exporter = StoreExporter(store)
    await exporter.export(normalized_batch)
    store.save_traces.assert_awaited_once()

@pytest.mark.asyncio
async def test_http_exporter_reuses_one_client(fake_transport, normalized_batch):
    exporter = HTTPExporter("http://retobs/api/production/traces", transport=fake_transport)
    await exporter.export(normalized_batch); await exporter.export(normalized_batch)
    assert exporter.client_creation_count == 1
    await exporter.close()
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_trace_exporters.py`

Expected: collection fails because `tracing.exporters` is absent.

- [ ] **Step 3: Implement exporters**

```python
class TraceExporter(Protocol):
    async def export(self, batch: Sequence[NormalizedTrace]) -> None: ...
    async def close(self) -> None: ...

class HTTPExporter:
    def __init__(self, endpoint: str, *, timeout_s: float = 3.0, transport=None):
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        self._endpoint = endpoint
        self.client_creation_count = 1

    async def export(self, batch):
        response = await self._client.post(self._endpoint, json={"traces": [item.payload for item in batch]})
        response.raise_for_status()

    async def close(self):
        await self._client.aclose()
```

`StoreExporter.export()` reconstructs `RetrievalTrace.from_dict()` and invokes one `save_traces()` call. `MemoryExporter` appends batches under a lock and is the test sink.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_trace_exporters.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/tracing/exporters.py tests/unit/test_trace_exporters.py
git commit -m "feat(telemetry): add reusable batch exporters"
```

### Task 4: Build the bounded queue worker

**Files:**
- Rewrite: `retrieval_observatory/tracing/sink.py`
- Test: `tests/unit/test_buffered_trace_sink.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `BufferedTraceSink.start()`, `offer(trace) -> bool`, `flush(timeout_s) -> FlushResult`, `shutdown(timeout_s) -> FlushResult`, `health()`.

- [ ] **Step 1: Write failing overflow, retry, and deadline tests**

```python
@pytest.mark.asyncio
async def test_drop_newest_never_blocks(trace_factory):
    sink = BufferedTraceSink(BlockingExporter(), TelemetryConfig(queue_capacity=1, batch_size=1))
    await sink.start()
    assert sink.offer(trace_factory(trace_id="one")) is True
    started = time.perf_counter()
    assert sink.offer(trace_factory(trace_id="two")) is False
    assert time.perf_counter() - started < 0.01
    assert sink.health().drop_reasons == {"queue_full": 1}

@pytest.mark.asyncio
async def test_shutdown_honors_deadline(trace_factory):
    sink = BufferedTraceSink(HangingExporter(), TelemetryConfig(shutdown_timeout_s=0.05))
    await sink.start(); sink.offer(trace_factory())
    result = await sink.shutdown(0.05)
    assert result.timed_out is True
    assert result.unflushed >= 1
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_buffered_trace_sink.py`

Expected: FAIL because current `StoreSink.emit()` awaits persistence and has no queue.

- [ ] **Step 3: Implement queue lifecycle**

```python
def offer(self, trace: RetrievalTrace) -> bool:
    normalized = normalize_trace(trace, limits=self.config.limits, redacted_keys=self.redacted_keys)
    if normalized.failed:
        self.counters.serialization_failed(1)
        return False
    try:
        self.queue.put_nowait(normalized)
        self.counters.accepted(1); self.counters.queue_depth(self.queue.qsize())
        return True
    except asyncio.QueueFull:
        if self.config.overflow_policy is OverflowPolicy.DROP_OLDEST:
            self.queue.get_nowait(); self.queue.task_done(); self.queue.put_nowait(normalized)
            self.counters.dropped("queue_full_oldest", 1); return True
        self.counters.dropped("queue_full", 1); return False
```

The worker waits for one item, fills up to `batch_size` without blocking, exports under `asyncio.timeout(export_timeout_s)`, retries exactly `max_retries` with `retry_base_s * 2**attempt + random.uniform(0, retry_base_s)`, and marks every queue item done exactly once. `shutdown()` stops acceptance, waits for `queue.join()` within the deadline, cancels the worker, closes the exporter, and returns counts without raising.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_buffered_trace_sink.py`

Expected: overflow, retries, batch, shutdown, and exporter-failure tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/tracing/sink.py tests/unit/test_buffered_trace_sink.py
git commit -m "feat(telemetry): export through a bounded background queue"
```

### Task 5: Make recorder and FastAPI integration failure-isolated

**Files:**
- Rewrite: `retrieval_observatory/tracing/recorder.py`
- Modify: `retrieval_observatory/tracing/__init__.py`
- Rewrite: `retrieval_observatory/tracing/integrations/fastapi.py`
- Test: `tests/integration/test_fastapi_telemetry_isolation.py`

**Interfaces:**
- Consumes: `BufferedTraceSink.offer()`.
- Produces: sole `TraceRecorder`; `init()`; `instrument_fastapi(app, recorder, query_extractor=None, excluded_paths=...)`.

- [ ] **Step 1: Write failing request-isolation test**

```python
def test_exporter_failure_does_not_change_response_or_wait(client_with_failing_exporter):
    started = time.perf_counter()
    response = client_with_failing_exporter.post("/retrieve", json={"query": "reset password"})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert response.json() == {"ids": ["doc-1"]}
    assert elapsed < 0.1
    assert client_with_failing_exporter.app.state.retobs.health().permanent_failures >= 1
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/integration/test_fastapi_telemetry_isolation.py`

Expected: FAIL because middleware currently awaits trace flush or uses incompatible recorder paths.

- [ ] **Step 3: Implement non-awaiting completion and lifespan**

```python
async def finish(self, context: TraceContext, *, status="OK", error=None) -> None:
    if not context.sampled:
        self.sink.counters.sampled_out(1)
        return
    try:
        self.sink.offer(context.build_trace(status=status, error=error))
    except BaseException:
        self.sink.counters.serialization_failed(1)

@asynccontextmanager
async def retobs_lifespan(app):
    await recorder.sink.start()
    try:
        yield
    finally:
        app.state.retobs_shutdown = await recorder.sink.shutdown(recorder.sink.config.shutdown_timeout_s)
```

Middleware creates trace scope, calls the host handler, records status/error, and invokes `finish()`; it never calls `flush()`. Expose only the V2-style `span()` API under the sole recorder name. `init()` builds `StoreExporter` + `BufferedTraceSink` by default and accepts a caller-supplied exporter/config.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/integration/test_fastapi_telemetry_isolation.py tests/unit/test_tracing_fastapi.py tests/unit/test_tracing.py`

Expected: all updated sole-recorder tests pass; failing exporter does not affect the response.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/tracing/recorder.py retrieval_observatory/tracing/__init__.py retrieval_observatory/tracing/integrations/fastapi.py tests/integration/test_fastapi_telemetry_isolation.py tests/unit/test_tracing_fastapi.py tests/unit/test_tracing.py
git commit -m "refactor(telemetry): isolate recording from request execution"
```

### Task 6: Persist/expose instrumentation health and secure local serving

**Files:**
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/cli.py:465-505`
- Test: `tests/unit/test_instrumentation_health_api.py`
- Test: `tests/unit/test_cli_serve_safety.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `InstrumentationHealth`.
- Produces: `save_instrumentation_health()`, `get_instrumentation_health()`, `GET /api/production/services/{service_id}/instrumentation-health`; localhost default.

- [ ] **Step 1: Write failing API and bind-default tests**

```python
def test_health_endpoint_returns_capture_limitations(client, seeded_health):
    response = client.get("/api/production/services/svc/instrumentation-health")
    assert response.status_code == 200
    body = response.json()
    assert body["evidence_class"] == "measured"
    assert body["drop_reasons"] == {"queue_full": 2}
    assert body["sample_rate"] == 0.5

def test_serve_defaults_to_loopback():
    result = CliRunner().invoke(app, ["serve", "--help"])
    assert "127.0.0.1" in result.stdout
    assert "0.0.0.0" not in result.stdout
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_instrumentation_health_api.py tests/unit/test_cli_serve_safety.py`

Expected: endpoint is 404 and CLI help shows `0.0.0.0`.

- [ ] **Step 3: Implement snapshots and safe bind behavior**

Store health snapshots keyed by `(service_id, observed_at)` with JSON counters and configured sample rate. The endpoint returns the latest snapshot plus:

```python
{"evidence_class": "measured", "method_version": "instrumentation-health/1",
 "sample_size": snapshot.accepted, "limitations": limitations,
 "unavailable_reason": None if snapshot else "no instrumentation health snapshot"}
```

Change `serve(host: str = typer.Option("127.0.0.1", "--host"), ...)`. When host is not loopback, print `Warning: dashboard read APIs are unauthenticated; bind remotely only on a trusted network.` before starting.

Add under `[Unreleased] / Changed`:

```markdown
- `tracing/`, `store/`, `dashboard/api.py` — isolate trace export behind a bounded queue and expose measured capture health.
- `cli.py` — bind `retobs serve` to `127.0.0.1` by default and warn on remote exposure.
```

- [ ] **Step 4: Run workstream regression gates**

Run: `pytest -q tests/unit/test_instrumentation_health.py tests/unit/test_trace_serialization.py tests/unit/test_trace_redaction.py tests/unit/test_trace_exporters.py tests/unit/test_buffered_trace_sink.py tests/integration/test_fastapi_telemetry_isolation.py tests/unit/test_instrumentation_health_api.py tests/unit/test_cli_serve_safety.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/store retrieval_observatory/dashboard/api.py retrieval_observatory/cli.py tests/unit/test_instrumentation_health_api.py tests/unit/test_cli_serve_safety.py CHANGELOG.md
git commit -m "feat(telemetry): expose health and default to local serving"
```

## Workstream acceptance gate

Run: `pytest -q tests/unit/test_instrumentation_health.py tests/unit/test_trace_serialization.py tests/unit/test_trace_redaction.py tests/unit/test_trace_exporters.py tests/unit/test_buffered_trace_sink.py tests/integration/test_fastapi_telemetry_isolation.py tests/unit/test_instrumentation_health_api.py tests/unit/test_cli_serve_safety.py`

Expected: all pass. Queue overflow and exporter outage do not block or fail application requests; shutdown is bounded; non-JSON and secret-bearing metadata cannot escape normalization; health loss is visible; serving defaults to loopback. Run `git diff --check`; expected: no output.
