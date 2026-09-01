# Retrieval Observatory Product Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every P0–P4 roadmap item in `docs/PRODUCT_AUDIT_AND_REDESIGN.md`, replacing the four-product prototype with a trustworthy, query-centered retrieval reliability workspace.

**Architecture:** Make `RetrievalTraceV2`, explicit workspace scope, and versioned evidence contracts the canonical data layer. Build graph, comparison, query, finding, and report services once, then make the SDK, CLI, MCP, dashboard, Markdown, HTML, and CI consume those services without independently reconstructing claims.

**Tech Stack:** Python 3.10+, asyncio, dataclasses/Pydantic, SQLite/PostgreSQL, Typer, FastAPI, React 18, TypeScript, Vite, Vitest, pytest, Playwright/browser E2E.

## Global Constraints

- Preserve existing serialized data through read-time adapters and migrations until the documented removal boundary.
- Persist facts and evidence provenance; use unavailable instead of an unsupported number or inferred topology.
- Require explicit baseline/candidate orientation and explicit workspace/database scope.
- Keep YAML as an advanced path; make a Python callable sufficient for first value.
- Update `CHANGELOG.md` under `[Unreleased]` after every user-visible structural or architectural slice.
- Use TDD for each trust fix and run focused tests before the full suite.
- Do not add new metrics, scenario families, or framework integrations beyond the approved roadmap.
- Do not start broad UI restructuring until P0 evidence contracts are stable.

---

### Task 1: Canonical execution timing and partial-trace contract (P0.1–P0.2)

**Files:**
- Modify: `retrieval_observatory/tracing/model_v2.py`
- Modify: `retrieval_observatory/pipeline/dag.py`
- Modify: `retrieval_observatory/sdk/observe.py`
- Modify: `retrieval_observatory/tracing/lift.py`
- Modify: `retrieval_observatory/types.py`
- Test: `tests/unit/test_dag_pipeline.py`
- Create: `tests/unit/test_dag_execution_contract.py`

**Interfaces:**
- Produces `TraceTiming(wall_clock_ms, critical_path_ms, operator_sum_ms, semantics_version=1)` serialized under `RetrievalTraceV2.timing`.
- Produces `RetrievalTraceV2` for `OK`, `ERROR`, and `TIMEOUT` results, including terminal span errors and last-known output.
- `PipelineResult.total_latency_ms` remains wall-clock latency for compatibility; `trace.total_latency_ms` remains a read alias for wall clock.

- [ ] **Step 1: Add failing contract tests**

```python
async def test_parallel_sources_overlap_and_record_three_latency_semantics():
    result = await _parallel_sleep_dag(delay_s=0.05).run(Query(query_id="q", text="q", k=10))
    assert result.trace_v2.timing.operator_sum_ms >= 100
    assert result.trace_v2.timing.wall_clock_ms < 90
    assert result.trace_v2.timing.critical_path_ms < 90

async def test_failed_node_returns_partial_error_trace():
    result = await _failing_dag().run(Query(query_id="q", text="q", k=10))
    assert result.status == "ERROR"
    assert result.trace_v2.status == "ERROR"
    assert any(span.status == "ERROR" and span.error for span in result.trace_v2.spans)
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `.venv/bin/pytest tests/unit/test_dag_execution_contract.py tests/unit/test_dag_pipeline.py -q`  
Expected: new timing/partial-trace assertions fail.

- [ ] **Step 3: Implement dependency-wave concurrency and timing**

```python
@dataclass
class TraceTiming:
    wall_clock_ms: float
    critical_path_ms: float
    operator_sum_ms: float
    semantics_version: int = 1
```

Execute all currently ready nodes with `asyncio.gather`, sort completed results by declaration order before persisting spans/snapshots, compute critical path from parent durations, and attach partial traces on exception/cancellation.

- [ ] **Step 4: Verify focused and execution/trace suites**

Run: `.venv/bin/pytest tests/unit/test_dag_execution_contract.py tests/unit/test_dag_pipeline.py tests/unit/test_trace_lift.py tests/unit/test_tracing.py -q`  
Expected: all pass.

- [ ] **Step 5: Update `CHANGELOG.md` with one `Changed` and one `Fixed` line**

### Task 2: Candidate identity and transition truth (P0.4)

**Files:**
- Modify: `retrieval_observatory/tracing/model_v2.py`
- Modify: `retrieval_observatory/pipeline/dag.py`
- Modify: `retrieval_observatory/sdk/observe.py`
- Modify: `retrieval_observatory/tracing/integrations/_duck_typed.py`
- Modify: `retrieval_observatory/tracing/candidate_history.py`
- Test: `tests/unit/test_candidate_history.py`
- Create: `tests/unit/test_candidate_identity_contract.py`

**Interfaces:**
- `Candidate` preserves `origin_op_ids` across descendants and records `input_rank`, `output_rank`, add/drop reason, and score components.
- Every fired non-source span records `inputs`; every output transition is derivable by document ID.

- [ ] **Step 1: Add failing source→fusion→rerank→filter lineage tests**
- [ ] **Step 2: Run `.venv/bin/pytest tests/unit/test_candidate_identity_contract.py -q` and confirm failure**
- [ ] **Step 3: Add pure transition helpers**

```python
def candidates_from_documents(docs: list[Document], *, op_id: str, inputs: list[Candidate]) -> list[Candidate]:
    """Preserve source origins and attach before/after rank for matching document IDs."""
```

- [ ] **Step 4: Use the helper in DAG, observe, and framework wrappers without changing document identity**
- [ ] **Step 5: Run candidate, DAG, integration-wrapper, and full trace tests**
- [ ] **Step 6: Add a concise `CHANGELOG.md` `Fixed` line**

### Task 3: PipelineGraphV2 union and exact-trace projection (P0.3)

**Files:**
- Modify: `retrieval_observatory/pipeline/graph_contract.py`
- Modify: `retrieval_observatory/pipeline/graph_projection.py`
- Modify: `retrieval_observatory/dashboard/pipeline_graph.schema.json`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/diagram/html.py`
- Modify: `retrieval_observatory/mcp/server.py`
- Test: `tests/unit/test_pipeline_graph.py`
- Test: `tests/unit/test_golden_topology.py`
- Create: `tests/unit/test_pipeline_graph_contract_v2.py`

**Interfaces:**
- `PipelineGraph.contract_version == 2`; `projection_mode` is `run_union` or `trace`.
- Nodes/edges carry observed count, coverage, status counts, fire rate, timing semantics, cache/error/timeout evidence, final-output designation, and provenance.

- [ ] **Step 1: Add failing multi-trace union tests with conditional/error-only nodes**
- [ ] **Step 2: Confirm the representative-trace implementation fails them**
- [ ] **Step 3: Implement union projection over all trace statuses and exact-trace projection**
- [ ] **Step 4: Update JSON schema and every Python consumer; remove consumer-side topology guessing**
- [ ] **Step 5: Run graph, diagram, API, MCP, and golden-topology tests**
- [ ] **Step 6: Update `CHANGELOG.md`**

### Task 4: Replay, attribution, and diagnostic honesty (P0.5–P0.6)

**Files:**
- Modify: `retrieval_observatory/tracing/replay.py`
- Modify: `retrieval_observatory/tracing/attribution.py`
- Modify: `retrieval_observatory/metrics/diagnostics.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/advisor/recommend.py`
- Test: `tests/unit/test_replay.py`
- Test: `tests/unit/test_replay_assumptions.py`
- Test: `tests/unit/test_operator_attribution_endpoint.py`
- Create: `tests/unit/test_diagnostic_evidence.py`

**Interfaces:**
- `MarginalResult.delta`, intervals, and p-values are nullable and null for `NOT_REPLAYABLE`.
- Diagnostic findings expose `evidence_class`, method/version, affected query, and reason.
- Replace `id_or_qrel_issue` with `qrel_not_in_corpus` and `not_retrieved_by_any_pipeline`.

- [ ] **Step 1: Add failing indeterminate attribution and actual corpus-ID tests**
- [ ] **Step 2: Confirm focused tests fail**
- [ ] **Step 3: Make unsupported replay results unavailable and immutable**
- [ ] **Step 4: Split diagnostic labels using explicit corpus IDs**
- [ ] **Step 5: Update API/advisor consumers and compatibility reads**
- [ ] **Step 6: Run replay/diagnostics/advisor suites and update changelog**

### Task 5: Reproducibility manifest and unified comparison engine (P0.7, P3.3)

**Files:**
- Modify: `retrieval_observatory/runner/manifest.py`
- Modify: `retrieval_observatory/metrics/comparison.py`
- Modify: `retrieval_observatory/metrics/significance.py`
- Modify: `retrieval_observatory/advisor/regression.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/cli.py`
- Test: `tests/unit/test_comparability.py`
- Test: `tests/unit/test_cli_compare.py`
- Create: `tests/unit/test_comparison_decision.py`

**Interfaces:**
- `ComparisonValidity(status: valid|warning|invalid, differences, missing_fields)`.
- `ComparisonDecision(verdict: improved|regressed|no_change|no_decision, validity, metrics, affected_queries)`.
- Manifest separately records query/corpus/qrel fingerprints, counts, models, config, git dirty state, hardware, cache, timeout/retry, label method, and Test Set lineage.

- [ ] **Step 1: Add failing missing/mismatched metadata and BH/effect-threshold tests**
- [ ] **Step 2: Implement typed manifest/validity/decision models with legacy adapters**
- [ ] **Step 3: Route Advisor, API, and CLI through the single comparison engine**
- [ ] **Step 4: Remove winner headlines for invalid/non-significant comparisons**
- [ ] **Step 5: Run manifest/comparison/advisor/CLI suites and update changelog**

### Task 6: Explicit workspace scope and unified query evidence (P0.8, P1.3)

**Files:**
- Create: `retrieval_observatory/evidence/__init__.py`
- Create: `retrieval_observatory/evidence/query.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Modify: `retrieval_observatory/mcp/server.py`
- Test: `tests/unit/test_dashboard_multi_db_api.py`
- Create: `tests/unit/test_query_evidence.py`

**Interfaces:**
- `QueryEvidence` joins scoped query text/qrels/provenance, run outcomes, traces/transitions, diagnostics, production matches, replay, and findings.
- Route: `GET /dbs/{db_id}/runs/{run_id}/queries/{query_id}/evidence` with pagination for traces/candidates.

- [ ] **Step 1: Add two-database tests that contain the same run/query IDs with different evidence**
- [ ] **Step 2: Implement the pure query evidence service and scoped route**
- [ ] **Step 3: Scope lineage, recommendations, Test Sets, and production-match endpoints or compatibility adapters**
- [ ] **Step 4: Update TypeScript client signatures so `dbId` is mandatory**
- [ ] **Step 5: Run multi-DB/API/MCP tests and update changelog**

### Task 7: TestSetSummary and store parity contracts (P0.9, P0.11)

**Files:**
- Modify: `retrieval_observatory/forge/types.py`
- Modify: `retrieval_observatory/forge/stress/suite.py`
- Modify: `retrieval_observatory/forge/generation/generator.py`
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Test: `tests/unit/test_forge_suite.py`
- Test: `tests/unit/test_store.py`
- Test: `tests/unit/test_store_postgres.py`
- Create: `tests/store_contract.py`

**Interfaces:**
- `TestSetSummary(contract_version, total_scenarios, total_queries, by_scenario, by_generator, validation)`.
- `BaseStore` becomes a runtime-checkable protocol/ABC for every operation used by evidence services.

- [ ] **Step 1: Add failing demo/normal summary parity and shared store contract tests**
- [ ] **Step 2: Implement the typed summary plus legacy-key reader**
- [ ] **Step 3: Extract shared serialization/schema helpers without rewriting backend-specific SQL**
- [ ] **Step 4: Run the same contract against SQLite and PostgreSQL when DSN is available**
- [ ] **Step 5: Run Forge/demo/store suites and update changelog**

### Task 8: Integration readiness and plan/apply/verify workflow (P0.10, P1.5, P3.2)

**Files:**
- Modify: `retrieval_observatory/integrations/detect.py`
- Modify: `retrieval_observatory/integrations/registry.py`
- Modify: `retrieval_observatory/integrations/wire.py`
- Modify: `retrieval_observatory/integrations/verify.py`
- Modify: `retrieval_observatory/cli.py`
- Modify: `retrieval_observatory/mcp/server.py`
- Test: `tests/unit/test_verify_checks.py`
- Test: `tests/unit/test_integrations_wire.py`
- Test: `tests/unit/test_integrations_detect.py`

**Interfaces:**
- States: `ready`, `partially_instrumented`, `not_verified`, `failed`.
- `IntegrationPlan` is read-only until explicit apply; includes detection evidence, confidence, minimal patch, dependencies/credentials/data flow, expected operators, and verification criteria.
- Capability matrix states whether graph, metrics, lineage, replay, attribution, drift, or basic traces are safe.

- [ ] **Step 1: Add failing false-green/no-run/identity/topology/timing tests**
- [ ] **Step 2: Derive top-level state and CLI exit code from required checks**
- [ ] **Step 3: Split integration into plan/apply/verify while preserving `wire` aliases**
- [ ] **Step 4: Label Python/HTTP/FastAPI/LangChain/LlamaIndex first-class and other wrappers supported examples**
- [ ] **Step 5: Add/repair reference integration fixtures and run all integration tests**
- [ ] **Step 6: Update changelog**

### Task 9: Callable-first evaluation, typed Run, and report model (P1.1, P4.1, P4.3)

**Files:**
- Modify: `retrieval_observatory/sdk/api.py`
- Modify: `retrieval_observatory/sdk/report.py`
- Modify: `retrieval_observatory/sdk/__init__.py`
- Modify: `retrieval_observatory/__init__.py`
- Modify: `retrieval_observatory/cli.py`
- Create: `retrieval_observatory/reporting.py`
- Test: `tests/unit/test_sdk.py`
- Create: `tests/unit/test_evaluate_cli.py`
- Create: `tests/unit/test_reports.py`

**Interfaces:**
- `retobs.evaluate(target, queries, corpus, qrels, **options) -> Run`.
- CLI `retobs evaluate module:symbol ...`; `run` remains a warning alias for config execution.
- One `ReportModel` renders terminal, JSON, Markdown, and standalone HTML.

- [ ] **Step 1: Add failing clean callable/CLI/report tests**
- [ ] **Step 2: Reuse the current benchmark runner and expose typed `Run`/`Comparison` wrappers**
- [ ] **Step 3: Implement concise verdict/next-action output and machine-readable JSON**
- [ ] **Step 4: Implement deterministic Markdown/HTML renderers with validity and evidence**
- [ ] **Step 5: Run SDK/CLI/report/package tests and update changelog**

### Task 10: Conclusion-first run, comparison, and query APIs (P1.2, P1.4, P1.6)

**Files:**
- Create: `retrieval_observatory/evidence/findings.py`
- Create: `retrieval_observatory/evidence/run.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/demo_context.py`
- Modify: `retrieval_observatory/cli.py`
- Test: `tests/unit/test_dashboard_demo_context.py`
- Create: `tests/integration/test_golden_workflow.py`

**Interfaces:**
- Run summary returns evidence health, key metrics, dominant supported issue, affected queries, responsible operator only when supportable, and next action.
- Comparison response uses explicit `baseline` and `candidate`; invalid comparisons return `no_decision`.
- Demo deterministically covers temporal regression → query → operator/candidate cause → validated fix.

- [ ] **Step 1: Add failing golden workflow API test**
- [ ] **Step 2: Implement typed run/findings services and replace ad hoc overview claims**
- [ ] **Step 3: Rebuild demo fixtures on canonical summary/comparison/query evidence**
- [ ] **Step 4: Verify every demo deep link and CTA target at API level**
- [ ] **Step 5: Run demo/end-to-end suites and update changelog**

### Task 11: Dashboard navigation and semantic design system (P2.1, P2.7, P2.8)

**Files:**
- Modify: `retrieval_observatory/dashboard/ui/src/App.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/routing.ts`
- Modify: `retrieval_observatory/dashboard/ui/src/components/AppShell.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/ModeRail.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/index.css`
- Create: `retrieval_observatory/dashboard/ui/src/components/HomePage.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/EvidenceStatus.tsx`
- Test: `retrieval_observatory/dashboard/ui/src/routing.test.ts`

**Interfaces:**
- Primary routes: Home, Runs, Compare, Queries, Production, Test Sets; integrations/settings are utilities.
- Old hash routes redirect while preserving run/query/service context.
- Semantic tokens replace module brand colors; shell collapses below 900 px.

- [ ] **Step 1: Add failing routing/old-route/mobile-shell tests**
- [ ] **Step 2: Implement route parser/serializer and shell navigation**
- [ ] **Step 3: Remove automatic tours and mode-colored hierarchy**
- [ ] **Step 4: Add responsive navigation, focus, and non-color state primitives**
- [ ] **Step 5: Run Vitest/build and update changelog**

### Task 12: Query, pipeline, and comparison debuggers (P2.2, P2.3, P2.4)

**Files:**
- Modify: `retrieval_observatory/dashboard/ui/src/components/RunQueryDetailPage.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/QueryDiffPage.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/QueryReplayScrubber.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/PipelineDagView.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/RunArchitecturePage.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/ComparePanel.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/RunOverviewPage.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/utils/queryEvidence.ts`
- Create: `retrieval_observatory/dashboard/ui/src/utils/queryEvidence.test.ts`

**Interfaces:**
- Query page order: text/qrels/provenance → outcomes/diff → exact operator path → candidate transitions → diagnostics → production matches → findings → reproduction.
- DAG supports union and exact-trace modes plus accessible table.
- Compare is validity-first and exposes effect/CI/n/q-value, segments, queries, topology/config/operator changes.

- [ ] **Step 1: Add data-contract tests for first divergence and candidate movement**
- [ ] **Step 2: Build the unified query page from the scoped evidence endpoint**
- [ ] **Step 3: Render PipelineGraphV2 without reconstructing topology**
- [ ] **Step 4: Rebuild comparison/query diff around baseline/candidate decision**
- [ ] **Step 5: Remove dead recommendation links and unbounded trace fetches**
- [ ] **Step 6: Run Vitest/build/browser golden workflow and update changelog**

### Task 13: Production and Test Sets integration (P2.5–P2.6)

**Files:**
- Modify: `retrieval_observatory/tracing/types.py`
- Modify: `retrieval_observatory/tracing/lift.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/components/TraceLensWorkspace.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/tracelens/*.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/ForgeWorkspace.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/forge/*.tsx`
- Test: `tests/integration/test_observe_roundtrip.py`
- Test: `tests/integration/test_golden_workflow.py`

**Interfaces:**
- New production ingestion uses V2; V1 reads lift through a compatibility boundary.
- Production routes encode service/time/filter/trace and expose method/baseline/sample/threshold.
- Test Sets show generator/qrel/judge/human provenance and link to exact runs/queries.

- [ ] **Step 1: Add failing V1-lift/V2-production and Test Set provenance tests**
- [ ] **Step 2: Make V2 canonical for new production traces and keep V1 read adapter**
- [ ] **Step 3: Add deep-linked hotspot/drift/trace routes with explicit evidence methods**
- [ ] **Step 4: Replace Forge branding/pages with Test Sets using typed summaries**
- [ ] **Step 5: Run production/Test Set/backend/UI/browser suites and update changelog**

### Task 14: Frontend state, accessibility, responsive, and performance gates (P2.9)

**Files:**
- Modify: `retrieval_observatory/dashboard/ui/package.json`
- Modify: `retrieval_observatory/dashboard/ui/vite.config.ts`
- Modify: `retrieval_observatory/dashboard/ui/src/App.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/AsyncState.tsx`
- Create: `tests/browser/test_dashboard_golden.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Shared loading/empty/error/partial/unavailable states.
- Lazy-loaded route chunks and paginated/virtualized large lists.
- Browser checks at 390, 768, and 1440 px plus keyboard and automated accessibility checks.

- [ ] **Step 1: Add failing page-state, responsive, and keyboard browser checks**
- [ ] **Step 2: Add shared state components and route-level code splitting**
- [ ] **Step 3: Paginate/virtualize traces, queries, and candidates; set bundle budgets**
- [ ] **Step 4: Add browser/accessibility jobs to CI without hiding failures**
- [ ] **Step 5: Run Vitest/build/browser checks and update changelog**

### Task 15: Public taxonomy, deprecation, and documentation (P3.1, P3.4, P3.5, P3.6)

**Files:**
- Modify: `retrieval_observatory/cli.py`
- Modify: `retrieval_observatory/mcp/server.py`
- Modify: `README.md`
- Modify: `docs/guides/README.md`
- Modify: `docs/integrations/AGENT_QUICKSTART.md`
- Modify: `CONTRIBUTING.md`
- Create: `docs/guides/evidence-and-trust.md`
- Create: `docs/guides/migration-0.5.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/unit/test_mcp_server.py`
- Test: `tests/unit/test_packaging.py`

**Interfaces:**
- Core CLI/MCP vocabulary matches Evaluate, Runs, Compare, Queries, Production, Test Sets, Integrations, and Reports.
- Legacy commands/tools warn with replacement and removal version; read compatibility remains.

- [ ] **Step 1: Add failing help/MCP/deprecation/link checks**
- [ ] **Step 2: Converge CLI/SDK/MCP names and demote low-level tools**
- [ ] **Step 3: Rewrite README/docs around one debugging story and truthful support levels**
- [ ] **Step 4: Add trust, privacy, security, conduct, migration, and contributor docs**
- [ ] **Step 5: Fix all Ruff findings and add Ruff/link checks to CI**
- [ ] **Step 6: Run CLI/MCP/package/link/Ruff/full suites and update changelog**

### Task 16: PR reports, demo media, and release credibility (P4.2, P4.4–P4.5)

**Files:**
- Modify: `.github/workflows/retrieval-ci.yml`
- Modify: `.github/workflows/publish.yml`
- Create: `.github/actions/retobs-report/action.yml`
- Create: `scripts/generate_demo_assets.py`
- Create: `docs/assets/README.md`
- Modify: `README.md`
- Test: `tests/unit/test_reports.py`
- Test: `tests/unit/test_packaging.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- CI emits Markdown and standalone HTML with IDs, validity, quality/latency/cost, significant regressions, affected queries, verdict/no-decision, and artifact link.
- Release checks validate links, wheel golden workflow, generated asset version, migration notes, and changelog.

- [ ] **Step 1: Add snapshot tests for PR Markdown/HTML and release metadata checks**
- [ ] **Step 2: Add report-producing composite action/workflow using the canonical report model**
- [ ] **Step 3: Add deterministic demo asset generation and current screenshots/recording instructions**
- [ ] **Step 4: Extend publish smoke to execute the callable golden workflow from the wheel**
- [ ] **Step 5: Run all test/build/browser/lint/link/package checks**
- [ ] **Step 6: Audit every launch checklist box against fresh evidence; leave unsupported claims unchecked and documented**

## Final Verification

- [ ] `.venv/bin/pytest -q` reports zero failures.
- [ ] `.venv/bin/ruff check retrieval_observatory tests` reports zero findings.
- [ ] `npm ci && npm run test -- --run && npm run build` succeeds.
- [ ] Browser golden workflow passes at 390, 768, and 1440 px with no console errors and keyboard-accessible primary actions.
- [ ] SQLite and available PostgreSQL contract suites pass.
- [ ] Markdown link check and clean-wheel golden workflow pass.
- [ ] `git diff --check` passes and every changed line maps to an audit roadmap item.
- [ ] `CHANGELOG.md` `[Unreleased]` contains one concise line per user-visible logical change.
