# Unified Trace and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace split V1/V2 and evaluation/production persistence with one validated `RetrievalTrace` identity and one typed store API.

**Architecture:** The current V2 candidate DAG becomes the sole trace model, renamed without a version suffix and extended with service, optional run, data-version, and capture identity. SQLite and PostgreSQL expose the same domain queries over one trace table; evaluation metrics and Production APIs consume those queries without compatibility branches.

**Tech Stack:** Python 3.10+, dataclasses, aiosqlite, asyncpg, JSON, pytest, pytest-asyncio

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

- Create `tracing/model.py`: sole trace/candidate/span/capture contract.
- Delete `tracing/model_v2.py`, `tracing/types.py`, and `tracing/lift.py` after imports move.
- Rewrite trace methods in `store/base.py`, `store/sqlite.py`, and `store/postgres.py`.
- Replace `store/migrate.py` with a one-time schema compatibility detector/reset command, not dual-read migration.
- Make `metrics/engine.py`, `runner/execute.py`, `dashboard/api.py`, and `evidence/query.py` trace-native.

### Task 1: Define the sole trace identity and validation contract

**Files:**
- Create: `retrieval_observatory/tracing/model.py`
- Test: `tests/unit/test_trace_identity_contract.py`

**Interfaces:**
- Consumes: semantic fields from `tracing/model_v2.py`.
- Produces: `Candidate`, `OperatorSpan`, `TraceTiming`, `CaptureMetadata`, `RetrievalTrace`, `critical_path_latency_ms()`.

- [ ] **Step 1: Write failing production/evaluation and graph-validation tests**

```python
def test_production_trace_has_service_without_run():
    trace = RetrievalTrace(
        trace_id="t1", service_id="search", run_id=None, query_id="q1", query_text="hello",
        pipeline_id="hybrid", spans=[OperatorSpan.source("bm25", "BM25", [])],
        final_op_ids=("bm25",), timestamp=datetime.now(timezone.utc),
    )
    assert trace.run_id is None
    assert trace.service_id == "search"

def test_trace_rejects_unknown_parent():
    with pytest.raises(ValueError, match="unknown parent missing"):
        RetrievalTrace(
            trace_id="t", service_id="svc", run_id="run", query_id="q", query_text="q",
            pipeline_id="pipe", spans=[OperatorSpan.source("dense", "Dense", [], parent_ids=("missing",))],
            final_op_ids=("dense",), timestamp=datetime.now(timezone.utc),
        )
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_trace_identity_contract.py`

Expected: collection fails because `tracing.model` does not exist.

- [ ] **Step 3: Implement the validated model**

```python
@dataclass(frozen=True)
class CaptureMetadata:
    instrumentation_version: str
    sample_rate: float = 1.0
    sampled: bool = True
    candidates_truncated: bool = False
    redacted_field_count: int = 0
    omitted_field_count: int = 0

@dataclass
class RetrievalTrace:
    trace_id: str
    service_id: str
    run_id: str | None
    query_id: str
    query_text: str
    pipeline_id: str
    spans: list[OperatorSpan]
    final_op_ids: tuple[str, ...]
    timestamp: datetime
    dataset_id: str | None = None
    corpus_version: str | None = None
    index_version: str | None = None
    request_id: str | None = None
    status: Literal["OK", "TIMEOUT", "ERROR"] = "OK"
    timing: TraceTiming | None = None
    capture: CaptureMetadata = field(default_factory=lambda: CaptureMetadata("1"))
    metadata: dict[str, Any] = field(default_factory=dict)
    error_traceback: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        ids = [span.op_id for span in self.spans]
        if len(ids) != len(set(ids)):
            raise ValueError("operator IDs must be unique within a trace")
        known = set(ids)
        for span in self.spans:
            for parent in span.parent_ids:
                if parent not in known:
                    raise ValueError(f"unknown parent {parent}")
        if not set(self.final_op_ids) <= known:
            raise ValueError("final operator IDs must exist in spans")
        validate_acyclic(self.spans)
        validate_candidate_ranks(self.spans)
        if self.timing is None:
            self.timing = TraceTiming.from_spans(self.spans)
```

Move existing `Candidate`, `OperatorSpan`, `TraceTiming`, serialization, and critical-path behavior into this file. Add `OperatorSpan.source()` solely as a test/user convenience; it still returns a normal span.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_trace_identity_contract.py tests/unit/test_pipeline_graph_contract_v2.py`

Expected: all tests pass after imports switch to `tracing.model`.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/tracing/model.py tests/unit/test_trace_identity_contract.py tests/unit/test_pipeline_graph_contract_v2.py
git commit -m "feat(tracing): define unified trace identity"
```

### Task 2: Define one typed trace query/store protocol

**Files:**
- Modify: `retrieval_observatory/store/base.py:1-190`
- Test: `tests/unit/test_store_contract.py`

**Interfaces:**
- Consumes: `RetrievalTrace` from Task 1.
- Produces: `TraceQuery`, `ServiceSummary`, `TopologyVariant`, `InstrumentationHealth`, and `BaseStore.save_trace()`, `save_traces()`, `get_trace()`, `list_traces()`, `list_services()`, `purge_traces()`.

- [ ] **Step 1: Add a failing protocol-shape test**

```python
def test_store_protocol_has_no_versioned_or_legacy_trace_methods():
    names = set(BaseStore.__dict__)
    assert {"save_trace", "save_traces", "get_trace", "list_traces", "list_services", "purge_traces"} <= names
    assert {"save_trace_v2", "get_trace_v2", "get_traces_v2", "save_traces_batch"}.isdisjoint(names)

def test_trace_query_supports_production_and_evaluation_scope():
    query = TraceQuery(service_id="svc", run_id=None, pipeline_id="pipe", limit=50, offset=0)
    assert query.service_id == "svc" and query.run_id is None
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_store_contract.py::test_store_protocol_has_no_versioned_or_legacy_trace_methods`

Expected: FAIL because versioned and legacy methods coexist.

- [ ] **Step 3: Implement domain query types and protocol**

```python
@dataclass(frozen=True)
class TraceQuery:
    service_id: str | None = None
    run_id: str | None = None
    pipeline_id: str | None = None
    query_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    status: str | None = None
    topology_hash: str | None = None
    limit: int = 200
    offset: int = 0

@runtime_checkable
class BaseStore(Protocol):
    async def save_trace(self, trace: RetrievalTrace) -> None: ...
    async def save_traces(self, traces: Sequence[RetrievalTrace]) -> None: ...
    async def get_trace(self, trace_id: str) -> RetrievalTrace | None: ...
    async def list_traces(self, query: TraceQuery) -> list[RetrievalTrace]: ...
    async def list_services(self) -> list[ServiceSummary]: ...
    async def list_topology_variants(self, query: TraceQuery) -> list[TopologyVariant]: ...
    async def get_instrumentation_health(self, service_id: str) -> InstrumentationHealth: ...
    async def purge_traces(self, query: TraceQuery) -> int: ...
```

Keep non-trace run, metric, dataset, and configuration methods unchanged in this task.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_store_contract.py::test_store_protocol_has_no_versioned_or_legacy_trace_methods tests/unit/test_store_contract.py::test_trace_query_supports_production_and_evaluation_scope`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/store/base.py tests/unit/test_store_contract.py
git commit -m "refactor(store): define unified trace query protocol"
```

### Task 3: Implement the unified SQLite schema and beta reset

**Files:**
- Modify: `retrieval_observatory/store/sqlite.py:1-500,1016-1140`
- Rewrite: `retrieval_observatory/store/migrate.py`
- Test: `tests/unit/test_store_unified_sqlite.py`

**Interfaces:**
- Consumes: Task 1 model and Task 2 protocol.
- Produces: SQLite implementation; `ensure_supported_schema(db_path: Path) -> None`; `reset_database(db_path: Path) -> None`.

- [ ] **Step 1: Write failing production visibility and old-schema rejection tests**

```python
@pytest.mark.asyncio
async def test_production_trace_is_listed_without_run(sqlite_store, production_trace):
    await sqlite_store.save_trace(production_trace)
    rows = await sqlite_store.list_traces(TraceQuery(service_id=production_trace.service_id))
    services = await sqlite_store.list_services()
    assert [row.trace_id for row in rows] == [production_trace.trace_id]
    assert services[0].service_id == production_trace.service_id

def test_old_dual_trace_schema_requires_reset(tmp_path):
    db = tmp_path / "old.db"
    create_old_traces_v2_table(db)
    with pytest.raises(IncompatibleSchemaError, match="retobs storage reset"):
        ensure_supported_schema(db)
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_store_unified_sqlite.py`

Expected: FAIL because production readers query the old `traces` table and reset detection is absent.

- [ ] **Step 3: Implement one indexed table and typed queries**

```sql
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    run_id TEXT,
    query_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    topology_hash TEXT NOT NULL,
    trace_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_service_time ON traces(service_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_traces_run_query ON traces(run_id, query_id);
CREATE INDEX IF NOT EXISTS idx_traces_pipeline_topology ON traces(pipeline_id, topology_hash);
```

```python
async def save_trace(self, trace: RetrievalTrace) -> None:
    await self.init_db()
    payload = json.dumps(trace.to_dict(), sort_keys=True)
    async with aiosqlite.connect(self.db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trace.trace_id, trace.service_id, trace.run_id, trace.query_id, trace.pipeline_id,
             trace.timestamp.isoformat(), trace.status, trace.topology_hash(), payload),
        )
        await db.commit()
```

Build `list_traces()` SQL from `TraceQuery` using bound parameters; never interpolate values. `list_services()` groups this same table. `ensure_supported_schema()` checks `PRAGMA user_version`; version `0` with old `traces_v2` or old V1 columns raises `IncompatibleSchemaError`. `reset_database()` removes only known retobs tables inside a transaction and sets the new schema version.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_store_unified_sqlite.py tests/unit/test_store_contract.py`

Expected: all SQLite contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/store/sqlite.py retrieval_observatory/store/migrate.py tests/unit/test_store_unified_sqlite.py tests/unit/test_store_contract.py
git commit -m "refactor(store): unify SQLite trace persistence"
```

### Task 4: Implement the same contract in PostgreSQL

**Files:**
- Modify: `retrieval_observatory/store/postgres.py:1-460,990-1140`
- Test: `tests/unit/test_store_postgres.py`

**Interfaces:**
- Consumes: Task 2 protocol.
- Produces: PostgreSQL methods with identical return types/filter semantics.

- [ ] **Step 1: Parameterize the existing shared contract**

```python
@pytest.fixture(params=["sqlite", "postgres"])
async def contract_store(request, tmp_path):
    store = await make_contract_store(request.param, tmp_path)
    await store.init_db()
    yield store
    await close_contract_store(store)

@pytest.mark.asyncio
async def test_store_contract_optional_run_and_filters(contract_store, production_trace, evaluation_trace):
    await contract_store.save_traces([production_trace, evaluation_trace])
    production = await contract_store.list_traces(TraceQuery(service_id="svc", run_id=None))
    evaluation = await contract_store.list_traces(TraceQuery(run_id="run-1"))
    assert production_trace.trace_id in {t.trace_id for t in production}
    assert [t.trace_id for t in evaluation] == [evaluation_trace.trace_id]
```

- [ ] **Step 2: Verify PostgreSQL failure**

Run: `RETOBS_TEST_POSTGRES=1 pytest -q tests/unit/test_store_contract.py`

Expected: PostgreSQL cases fail because old `traces` and `traces_v2` methods do not implement `TraceQuery`.

- [ ] **Step 3: Implement PostgreSQL table and methods**

Use the Task 3 columns with `TIMESTAMPTZ`, `JSONB`, and `$1` parameters. Implement `save_traces()` with one transaction and `executemany`; implement the same filter order and pagination as SQLite. Compute topology hashes in Python so both stores produce identical values.

```python
async def get_trace(self, trace_id: str) -> RetrievalTrace | None:
    row = await self._pool.fetchrow("SELECT trace_json FROM traces WHERE trace_id = $1", trace_id)
    return RetrievalTrace.from_dict(dict(row["trace_json"])) if row else None
```

- [ ] **Step 4: Verify parity**

Run: `RETOBS_TEST_POSTGRES=1 pytest -q tests/unit/test_store_contract.py tests/unit/test_store_postgres.py`

Expected: SQLite and PostgreSQL cases pass with identical assertions.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/store/postgres.py tests/unit/test_store_contract.py tests/unit/test_store_postgres.py
git commit -m "refactor(store): align PostgreSQL trace contract"
```

### Task 5: Make evaluation and metrics trace-native

**Files:**
- Modify: `retrieval_observatory/runner/execute.py:150-215`
- Modify: `retrieval_observatory/metrics/engine.py:298-520`
- Modify: `retrieval_observatory/evidence/query.py:1-130`
- Test: `tests/integration/test_trace_native_evaluation.py`

**Interfaces:**
- Consumes: unified store and `RetrievalTrace`.
- Produces: evaluation runs persist traces first and compute all metrics/evidence from them.

- [ ] **Step 1: Write a failing no-raw-result evaluation test**

```python
@pytest.mark.asyncio
async def test_evaluation_persists_trace_before_metrics(tiny_config, sqlite_store, monkeypatch):
    monkeypatch.setattr(sqlite_store, "save_result", lambda *args: pytest.fail("save_result must not be used"), raising=False)
    report = await execute_experiment(tiny_config, store=sqlite_store)
    traces = await sqlite_store.list_traces(TraceQuery(run_id=report.run_id))
    assert traces
    assert await MetricsEngine().aggregate(report.run_id, sqlite_store)
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/integration/test_trace_native_evaluation.py`

Expected: FAIL because `runner/execute.py` still saves and diagnoses `PipelineResult` objects.

- [ ] **Step 3: Persist traces as the canonical evidence**

```python
traces: list[RetrievalTrace] = []
for result in all_results:
    if result.trace is None:
        raise RuntimeError(f"pipeline {result.pipeline_id} returned no execution trace")
    trace = result.trace.with_identity(run_id=run_id, service_id=experiment_name)
    traces.append(trace)
await store.save_traces(traces)
await engine.compute_from_traces(run_id, store, traces, qrels)
diagnostics = build_trace_diagnostics(run_id, traces, qrels, corpus_doc_ids=corpus_doc_ids)
await store.save_query_diagnostics(diagnostics)
```

Remove metric fallback conversion from `_CompatResult`; query evidence loads traces through `TraceQuery(run_id=..., query_id=...)`.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/integration/test_trace_native_evaluation.py tests/unit/test_metric_parity.py tests/unit/test_query_evidence_scope.py`

Expected: all tests pass with no `save_result()` call.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/runner/execute.py retrieval_observatory/metrics/engine.py retrieval_observatory/evidence/query.py tests/integration/test_trace_native_evaluation.py
git commit -m "refactor(evaluation): compute from unified traces"
```

### Task 6: Port Production APIs and delete V1/V2 compatibility code

**Files:**
- Modify: `retrieval_observatory/dashboard/api.py:130-180,475-540,818-1125,1545-1660`
- Modify: `retrieval_observatory/tracing/__init__.py`
- Modify: `retrieval_observatory/tracing/sink.py`
- Delete: `retrieval_observatory/tracing/types.py`
- Delete: `retrieval_observatory/tracing/model_v2.py`
- Delete: `retrieval_observatory/tracing/lift.py`
- Delete: `tests/unit/test_trace_lift.py`
- Test: `tests/integration/test_production_trace_dashboard_roundtrip.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: run and Production APIs over the same trace rows; no versioned methods/imports.

- [ ] **Step 1: Write the failing API round-trip test**

```python
def test_production_trace_is_visible_without_run(client, store, production_trace):
    asyncio.run(store.save_trace(production_trace))
    services = client.get("/api/production/services").json()
    traces = client.get(f"/api/production/traces?service_id={production_trace.service_id}").json()
    assert services[0]["service_id"] == production_trace.service_id
    assert traces[0]["trace_id"] == production_trace.trace_id
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/integration/test_production_trace_dashboard_roundtrip.py`

Expected: FAIL because Production endpoints read V1 `traces` semantics and V2 writes are separate.

- [ ] **Step 3: Port endpoints and remove compatibility branches**

Production ingestion parses `RetrievalTrace.from_dict()` and calls `save_traces()`. Listing builds `TraceQuery`; run trace routes pass `run_id`. Delete `_CompatResult`, all `hasattr(...get_traces_v2)` branches, V1 serialization, `TraceRecorder` legacy exports, and lift/migration imports. Rename user-visible payload fields from `trace_format_version` to `schema_version`.

Add under `[Unreleased] / Changed`:

```markdown
- `tracing/`, `store/`, `dashboard/api.py` — replace split V1/V2 trace paths with one service-aware trace and storage contract.
```

- [ ] **Step 4: Run deletion and regression gates**

Run: `pytest -q tests/integration/test_production_trace_dashboard_roundtrip.py tests/unit/test_store_contract.py tests/unit/test_dashboard_multi_db_api.py tests/unit/test_query_evidence_scope.py`

Expected: all tests pass.

Run: `rg -n "RetrievalTraceV2|TraceRecorderV2|LegacyTraceRecorder|traces_v2|get_traces_v2|save_trace_v2" retrieval_observatory tests`

Expected: exit code 1 with no output.

- [ ] **Step 5: Commit**

```bash
git add -A retrieval_observatory/tracing retrieval_observatory/store retrieval_observatory/dashboard/api.py tests CHANGELOG.md
git commit -m "refactor(tracing): remove split trace compatibility paths"
```

## Workstream acceptance gate

Run: `pytest -q tests/unit/test_trace_identity_contract.py tests/unit/test_store_contract.py tests/unit/test_store_unified_sqlite.py tests/unit/test_store_postgres.py tests/integration/test_trace_native_evaluation.py tests/integration/test_production_trace_dashboard_roundtrip.py`

Expected: all supported-store tests pass. Then run `rg -n "RetrievalTraceV2|TraceRecorderV2|LegacyTraceRecorder|traces_v2" retrieval_observatory tests`; expected: no output. Run `git diff --check`; expected: no output.
