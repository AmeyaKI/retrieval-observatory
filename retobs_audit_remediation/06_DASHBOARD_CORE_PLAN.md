# Dashboard Core Scale and Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every existing dashboard workflow globally scoped, URL-addressable, searchable, cohort-ready, and understandable at production scale.

**Architecture:** A single URL-backed `DashboardContext` owns database, service, run, time window, cohort, and filters. Existing workspaces consume that context, while Production and Architecture use paginated trace-search and topology-variant APIs instead of loading opaque fixed-size lists. Compare and Test Sets retain their current evidence semantics but expose decision dimensions and provenance explicitly.

**Tech Stack:** React 18, TypeScript 5.5, the existing zero-dependency hash router, Recharts 2, Tailwind CSS, FastAPI, Python 3.10+, unified `RetrievalTrace`/`BaseStore` contracts from workstream 2, Vitest, pytest, Playwright, axe-core.

## Global Constraints

- This plan depends on workstreams 2, 3, 4, and 5; do not add adapters for removed V1 tables, recorder types, or endpoints.
- Use only the unified `RetrievalTrace` and domain store APIs; no `V2` suffix may appear in new public API or UI names.
- Remove legacy route migration rather than preserving aliases; the clean beta reset explicitly permits breaking routes.
- Primary pages remain Home, Runs, Compare, Queries, Production, and Test Sets.
- Global context keys are exactly `db`, `service`, `run`, `window`, `since`, `until`, `cohort`, and repeated `filter` values.
- Every unavailable state must state which evidence is missing and what action produces it.
- Do not add a routing or state-management dependency; extend the existing hash router and React context.
- API list endpoints return a typed envelope with `items`, `total`, `limit`, `offset`, and `next_offset`.
- Dashboard servers bind to `127.0.0.1` by default under workstream 3; this plan must not weaken that rule.
- Update `CHANGELOG.md` under `[Unreleased]` for each user-visible task.
- Each task is complete only after its focused Python/UI tests pass and `npm run build` succeeds.

---

## Target File Map

**Create**

- `retrieval_observatory/dashboard/ui/src/context/DashboardContext.tsx` — canonical URL-backed dashboard selection state.
- `retrieval_observatory/dashboard/ui/src/context/DashboardContext.test.tsx` — parsing, persistence, navigation, and invalid-context tests.
- `retrieval_observatory/dashboard/ui/src/components/GlobalContextBar.tsx` — visible database/service/run/window/cohort controls.
- `retrieval_observatory/dashboard/ui/src/components/production/ProductionRouter.tsx` — route matcher for Production subviews.
- `retrieval_observatory/dashboard/ui/src/components/TraceSearchControl.tsx` — debounced, paginated trace lookup.
- `retrieval_observatory/dashboard/ui/src/components/TopologyVariantList.tsx` — variant frequency/coverage summary and drill-down.
- `retrieval_observatory/dashboard/ui/src/components/DecisionDimensions.tsx` — separate statistical/practical/power/release states.
- `retrieval_observatory/dashboard/ui/src/components/CollapsibleEvidenceSection.tsx` — accessible persisted disclosure for long Compare sections.
- `tests/unit/test_dashboard_trace_search.py` — trace search API contract.
- `tests/unit/test_dashboard_topology_variants.py` — topology grouping contract.
- `tests/unit/test_dashboard_testset_queries.py` — Test Set pagination/provenance contract.

**Modify**

- `retrieval_observatory/dashboard/ui/src/App.tsx` — mount the provider.
- `retrieval_observatory/dashboard/ui/src/routing.ts` and `routing.test.ts` — typed query arrays and canonical routes; delete legacy migration.
- `retrieval_observatory/dashboard/ui/src/components/AppShell.tsx` — consume global context and render `GlobalContextBar`.
- `retrieval_observatory/dashboard/ui/src/components/BenchmarksWorkspace.tsx`, `DbTabs.tsx`, `RunsSidebar.tsx` — remove private database ownership.
- `retrieval_observatory/dashboard/ui/src/components/TraceLensWorkspace.tsx` — rename to `ProductionWorkspace.tsx`, use routed subviews and global window.
- `retrieval_observatory/dashboard/ui/src/components/tracelens/*.tsx` — move to `components/production/`, consume canonical pagination/window contracts.
- `retrieval_observatory/dashboard/ui/src/components/ForgeWorkspace.tsx` and `components/forge/*.tsx` — rename to Test Set terminology and expose identity/provenance.
- `retrieval_observatory/dashboard/ui/src/components/PipelineDagView.tsx` — replace fixed trace select with variants/search.
- `retrieval_observatory/dashboard/ui/src/components/ComparePanel.tsx` and `RunComparisonDeepDiffs.tsx` — decision dimensions, filters, and collapsed sections.
- `retrieval_observatory/dashboard/ui/src/components/RunQueryDetailPage.tsx` — aggregate production matches before trace drill-down.
- `retrieval_observatory/dashboard/ui/src/api.ts` — typed context, pagination, trace search, variant, Compare, Test Set contracts.
- `retrieval_observatory/dashboard/api.py` — scoped trace-search, topology-variant, production-match, and Test Set envelopes.
- `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py` — domain query implementations and parity.
- `tests/browser/test_dashboard_workflow.py` — deep links, global context, scaling, responsive and WCAG proof.
- `CHANGELOG.md` — one line per user-visible task.

### Task 1: Canonical URL-Backed Dashboard Context

**Files:**
- Create: `retrieval_observatory/dashboard/ui/src/context/DashboardContext.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/context/DashboardContext.test.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/routing.ts`
- Modify: `retrieval_observatory/dashboard/ui/src/routing.test.ts`
- Modify: `retrieval_observatory/dashboard/ui/src/App.tsx`

**Interfaces:**
- Consumes: `DbSource`, `Run`, and `fetchDbs()` from `dashboard/ui/src/api.ts`.
- Produces: `DashboardSelection`, `DashboardContextValue`, `DashboardProvider`, `useDashboardContext()`, `parseDashboardQuery()`, and `serializeDashboardQuery()`.

```ts
export interface DashboardSelection {
  db: string | null
  service: string | null
  run: string | null
  window: '24h' | '7d' | '30d' | 'all' | 'custom'
  since: string | null
  until: string | null
  cohort: string | null
  filters: string[]
}

export interface DashboardContextValue {
  selection: DashboardSelection
  databases: DbSource[]
  updateSelection(patch: Partial<DashboardSelection>, mode?: 'push' | 'replace'): void
}
```

- [ ] **Step 1: Write failing context and routing tests**

```tsx
it('round-trips every global context field and repeated filters', () => {
  const selection = parseDashboardQuery('db=prod&service=search&run=r1&window=custom&since=2026-07-01T00%3A00%3A00Z&until=2026-07-02T00%3A00%3A00Z&cohort=hard&filter=status%3AERROR&filter=route%3Alegal')
  expect(selection.filters).toEqual(['status:ERROR', 'route:legal'])
  expect(parseDashboardQuery(serializeDashboardQuery(selection))).toEqual(selection)
})

it('falls back to the first available database only when db is absent', async () => {
  window.location.hash = '#/production?db=secondary'
  render(<DashboardProvider><Probe /></DashboardProvider>)
  await screen.findByText('secondary')
  expect(window.location.hash).toContain('db=secondary')
})
```

- [ ] **Step 2: Run the tests and confirm the missing contract**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/context/DashboardContext.test.tsx src/routing.test.ts`

Expected: FAIL because `DashboardContext` and repeated-query parsing do not exist.

- [ ] **Step 3: Implement deterministic query parsing and provider ownership**

Implement `parseDashboardQuery` with `URLSearchParams.getAll('filter')`; validate `window`; preserve an explicit valid `db`; replace only invalid or absent database IDs after `fetchDbs()`. `updateSelection` must retain the current path, sort filters, omit null values, and use `history.pushState` or `replaceState` followed by a `hashchange` event.

```tsx
export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [databases, setDatabases] = useState<DbSource[]>([])
  const [selection, setSelection] = useState(() => parseDashboardQuery(hashQuery()))
  // Listen to hashchange, load databases once, and canonicalize invalid db IDs.
  return <DashboardContext.Provider value={{ selection, databases, updateSelection }}>{children}</DashboardContext.Provider>
}
```

Delete `migrateLegacyPath` and its tests. Canonical invalid paths resolve to Home; old `benchmarks`, `tracelens`, `forge`, and `advisor` hashes are not translated.

- [ ] **Step 4: Mount the provider and run focused tests**

```tsx
export default function App() {
  return <DashboardProvider><AppShell /></DashboardProvider>
}
```

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/context/DashboardContext.test.tsx src/routing.test.ts`

Expected: both test files PASS; explicit database selection survives a refresh and repeated filters round-trip.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/dashboard/ui/src/App.tsx retrieval_observatory/dashboard/ui/src/context retrieval_observatory/dashboard/ui/src/routing.ts retrieval_observatory/dashboard/ui/src/routing.test.ts CHANGELOG.md
git commit -m "feat: add URL-backed dashboard context"
```

### Task 2: Global Context Bar and Workspace Convergence

**Files:**
- Create: `retrieval_observatory/dashboard/ui/src/components/GlobalContextBar.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/AppShell.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/BenchmarksWorkspace.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/DbTabs.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/ForgeWorkspace.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/TraceLensWorkspace.tsx`
- Test: `retrieval_observatory/dashboard/ui/src/context/DashboardContext.test.tsx`

**Interfaces:**
- Consumes: `useDashboardContext()` from Task 1 and existing `fetchRuns`, `fetchTraceServices`.
- Produces: one visible `GlobalContextBar` and workspaces with no private database selection state.

- [ ] **Step 1: Add a failing cross-workspace persistence test**

```tsx
it('keeps the selected database while moving from Runs to Production and Test Sets', async () => {
  render(<DashboardProvider><AppShell /></DashboardProvider>)
  await user.selectOptions(screen.getByLabelText('Database'), 'secondary')
  await user.click(screen.getByRole('button', { name: 'Production' }))
  expect(window.location.hash).toContain('db=secondary')
  await user.click(screen.getByRole('button', { name: 'Test Sets' }))
  expect(screen.getByLabelText('Database')).toHaveValue('secondary')
})
```

- [ ] **Step 2: Run it and confirm current split ownership fails**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/context/DashboardContext.test.tsx`

Expected: FAIL because `AppShell` and `BenchmarksWorkspace` maintain separate database state.

- [ ] **Step 3: Implement the context bar and remove private database ownership**

`GlobalContextBar` renders database always, and service/run/window/cohort only when meaningful. A changed database clears incompatible service/run/cohort fields in one `updateSelection` call. `BenchmarksWorkspace` receives `dbId` from context, and selection changes update `run`. Production and Test Sets read the same `db`.

```tsx
<select aria-label="Database" value={selection.db ?? ''}
  onChange={(e) => updateSelection({ db: e.target.value, service: null, run: null, cohort: null })}>
  {databases.map((db) => <option key={db.db_id} value={db.db_id}>{db.label}</option>)}
</select>
```

- [ ] **Step 4: Verify state behavior and production build**

Run: `cd retrieval_observatory/dashboard/ui && npm test -- --run src/context/DashboardContext.test.tsx && npm run build`

Expected: context tests PASS; TypeScript and Vite build PASS; no workspace calls `fetchDbs()` except the provider.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/dashboard/ui/src/components retrieval_observatory/dashboard/ui/src/context CHANGELOG.md
git commit -m "refactor: unify dashboard workspace context"
```

### Task 3: Route Every Production Subview and Time Window

**Files:**
- Create: `retrieval_observatory/dashboard/ui/src/components/production/ProductionRouter.tsx`
- Move: `retrieval_observatory/dashboard/ui/src/components/TraceLensWorkspace.tsx` to `retrieval_observatory/dashboard/ui/src/components/ProductionWorkspace.tsx`
- Move: `retrieval_observatory/dashboard/ui/src/components/tracelens/*.tsx` to `retrieval_observatory/dashboard/ui/src/components/production/`
- Modify: `retrieval_observatory/dashboard/ui/src/components/AppShell.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/routing.test.ts`

**Interfaces:**
- Consumes: global `service`, `window`, `since`, and `until`; existing production fetch functions.
- Produces: canonical routes `production/:service/:view` where `view` is `overview|traces|distribution|drift|hotspots|clusters`.

- [ ] **Step 1: Add failing route and refresh tests**

```ts
it('matches a production subview and retains its window', () => {
  const match = PRODUCTION_ROUTES.match('search/drift?window=24h')
  expect(match).toEqual({ routeId: ':service/:view', params: { service: 'search', view: 'drift' }, query: { window: '24h' } })
})
```

Add a component test that initializes `#/production/search/hotspots?db=prod&window=30d`, remounts the router, and still renders the Hotspots heading with `30d` selected.

- [ ] **Step 2: Run and confirm local view state loses the route**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/routing.test.ts src/components/production/ProductionRouter.test.tsx`

Expected: FAIL because Production view/window are component-local.

- [ ] **Step 3: Implement route-owned view and absolute windows**

`ProductionRouter` validates the view. `window=24h|7d|30d|all` computes `since` at request time; `window=custom` requires valid ISO `since` and optional `until`, otherwise renders an invalid-context `StatusPanel`. All view links include service and view in the path and context in the query.

- [ ] **Step 4: Verify routes, back/forward, and build**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/routing.test.ts src/components/production/ProductionRouter.test.tsx && npm run build`

Expected: direct links, refresh, browser back/forward, and custom-window validation PASS.

- [ ] **Step 5: Commit the clean terminology and routes**

```bash
git add retrieval_observatory/dashboard/ui/src/components retrieval_observatory/dashboard/ui/src/routing.test.ts CHANGELOG.md
git commit -m "feat: deep-link production investigations"
```

### Task 4: Paginated Trace Search and Topology Variants

**Files:**
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Create: `tests/unit/test_dashboard_trace_search.py`
- Create: `tests/unit/test_dashboard_topology_variants.py`

**Interfaces:**
- Consumes: unified `RetrievalTrace`, stable `op_id`/`parent_ids`, production/evaluation identity from workstreams 2 and 4.
- Produces:

```python
class TraceSearchPage(TypedDict):
    items: list[dict]
    total: int
    limit: int
    offset: int
    next_offset: int | None

async def search_traces(*, service: str | None, run_id: str | None, text: str | None,
                        query_id: str | None, status: str | None, operator_id: str | None,
                        topology_id: str | None, since: str | None, until: str | None,
                        cohort_predicate: dict | None, limit: int, offset: int) -> TraceSearchPage: ...

async def list_topology_variants(*, service: str | None, run_id: str | None,
                                 since: str | None, until: str | None,
                                 cohort_predicate: dict | None) -> list[dict]: ...
```

Topology fingerprint is SHA-256 over sorted tuples `(op_id, op_type, status, sorted(parent_ids))`; response fields are `topology_id`, `trace_count`, `share`, `status_counts`, `operator_ids`, `edge_count`, `example_trace_ids`, and `evidence`.

- [ ] **Step 1: Write positive, paginated, and invalid-filter API tests**

```python
@pytest.mark.asyncio
async def test_trace_search_is_scoped_and_paginated(seeded_registry):
    response = await client.get('/dbs/main/traces/search', params={
        'run_id': 'r1', 'text': 'temporal', 'limit': 2, 'offset': 0,
    })
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'items', 'total', 'limit', 'offset', 'next_offset'}
    assert body['limit'] == 2
    assert all('temporal' in row['query_text'].lower() for row in body['items'])

@pytest.mark.asyncio
async def test_topology_variants_group_identical_dags(seeded_registry):
    body = (await client.get('/dbs/main/topology-variants', params={'run_id': 'r1'})).json()
    assert sum(row['trace_count'] for row in body['items']) == 3
    assert body['items'][0]['topology_id'].startswith('sha256:')
    assert len(body['items'][0]['example_trace_ids']) <= 3
```

- [ ] **Step 2: Run tests and verify endpoints are absent**

Run: `pytest -q tests/unit/test_dashboard_trace_search.py tests/unit/test_dashboard_topology_variants.py`

Expected: FAIL with 404 for both new endpoints.

- [ ] **Step 3: Implement store parity and thin API validation**

Use parameterized SQL for indexed scalar filters, deserialize only the bounded candidate rows needed for operator/topology/cohort predicates, and run a separate count query. Reject `limit` outside `1..200`, negative offset, simultaneous missing `service` and `run_id`, invalid status, and malformed timestamps with HTTP 422. PostgreSQL and SQLite return identical ordering: timestamp descending then trace ID ascending.

- [ ] **Step 4: Run contract and store parity tests**

Run: `pytest -q tests/unit/test_dashboard_trace_search.py tests/unit/test_dashboard_topology_variants.py tests/unit/test_store_contract.py tests/unit/test_store_postgres.py`

Expected: PASS; SQLite/PostgreSQL contract cases return identical envelopes and fingerprints.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/store retrieval_observatory/dashboard tests/unit/test_dashboard_trace_search.py tests/unit/test_dashboard_topology_variants.py CHANGELOG.md
git commit -m "feat: add trace search and topology variants"
```

### Task 5: Searchable Architecture Projection and Variant Drill-Down

**Files:**
- Create: `retrieval_observatory/dashboard/ui/src/components/TraceSearchControl.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/TopologyVariantList.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/PipelineDagView.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Test: `retrieval_observatory/dashboard/ui/src/components/TraceSearchControl.test.tsx`
- Test: `retrieval_observatory/dashboard/ui/src/components/TopologyVariantList.test.tsx`

**Interfaces:**
- Consumes: `fetchTraceSearch(...)`, `fetchTopologyVariants(...)`, `fetchPipelineGraphs(...)`.
- Produces: debounced search with accessible listbox, variant summary, and exact-trace projection selected by URL `filter=trace:<id>`.

- [ ] **Step 1: Write failing scaling tests**

```tsx
it('searches rather than rendering fifty opaque options', async () => {
  render(<TraceSearchControl scope={{ db: 'main', run: 'r1' }} onSelect={onSelect} />)
  await user.type(screen.getByRole('searchbox', { name: 'Find trace' }), 'policy renewal')
  await waitFor(() => expect(fetchTraceSearch).toHaveBeenLastCalledWith(expect.objectContaining({ text: 'policy renewal', limit: 20 })))
  expect(screen.getAllByRole('option')).toHaveLength(2)
})

it('renders topology share and drills into a representative trace', async () => {
  render(<TopologyVariantList variants={[variant]} onOpenTrace={onOpenTrace} />)
  expect(screen.getByText('63.0%')).toBeVisible()
  await user.click(screen.getByRole('button', { name: /open example trace/i }))
  expect(onOpenTrace).toHaveBeenCalledWith('trace-1')
})
```

- [ ] **Step 2: Run tests and confirm components are missing**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/components/TraceSearchControl.test.tsx src/components/TopologyVariantList.test.tsx`

Expected: FAIL because both components are absent.

- [ ] **Step 3: Implement search, pagination, and variant-first architecture**

Debounce text by 250 ms, cancel stale requests with `AbortController`, show query text/query ID/status/timestamp/topology, and request the next page only from an explicit “Load more” button. `PipelineDagView` defaults to variant summary plus run union; selecting an example renders exact trace and a “Back to variant” control. Extract `GraphSvg`, `GraphTable`, and `NodeInspector` into named exports for workstream 7 reuse.

- [ ] **Step 4: Run UI tests and build**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/components/TraceSearchControl.test.tsx src/components/TopologyVariantList.test.tsx src/utils/dagLayout.test.ts && npm run build`

Expected: PASS; no fixed `fetchRunTraces(..., 50)` call remains in `PipelineDagView.tsx`.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/dashboard/ui/src/components retrieval_observatory/dashboard/ui/src/api.ts CHANGELOG.md
git commit -m "feat: scale architecture trace selection"
```

### Task 6: Compare Decision Clarity and Progressive Disclosure

**Files:**
- Create: `retrieval_observatory/dashboard/ui/src/components/DecisionDimensions.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/CollapsibleEvidenceSection.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/ComparePanel.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/RunComparisonDeepDiffs.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Test: `retrieval_observatory/dashboard/ui/src/components/DecisionDimensions.test.tsx`
- Test: `retrieval_observatory/dashboard/ui/src/components/ComparePanel.test.tsx`

**Interfaces:**
- Consumes: current comparison `statistics` fields: `effect`, `effect_threshold`, `p_value`, `q_value`, `paired_n`, `low_power`, `significant`, `decision`, and `reason`.
- Produces: `DecisionDimension` values with states `pass|fail|unavailable` for `detectable`, `meaningful`, `powered`, `multiplicity_valid`, and `release_eligible`.

- [ ] **Step 1: Write the decision truth-table tests**

```tsx
it('does not call a tiny significant effect release eligible', () => {
  render(<DecisionDimensions statistics={{
    effect: 0.001, effect_threshold: 0.01, p_value: 0.0001, q_value: 0.001,
    paired_n: 1000, low_power: false, significant: true,
    decision: 'no_decision', reason: 'effect below threshold',
    baseline_mean: 0.4, candidate_mean: 0.401,
  }} />)
  expect(screen.getByText('Statistically detectable')).toHaveAttribute('data-state', 'pass')
  expect(screen.getByText('Practically meaningful')).toHaveAttribute('data-state', 'fail')
  expect(screen.getByText('Release eligible')).toHaveAttribute('data-state', 'fail')
})
```

- [ ] **Step 2: Run tests and observe the conflated q-value UI**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/components/DecisionDimensions.test.tsx src/components/ComparePanel.test.tsx`

Expected: FAIL because the decision dimensions are not rendered separately.

- [ ] **Step 3: Implement dimensions, filters, and collapsed deep sections**

Keep the metric table, add filters `decision-bearing`, `quality`, `latency`, `other`, and render q-value without an asterisk. Expand a selected metric into `DecisionDimensions`. Wrap query/topology/attribution/recommendation/config differences in accessible `<details>`-based sections; open only query winners by default. Persist open state in `sessionStorage` under `compare:<baseline>:<candidate>:<section>`.

- [ ] **Step 4: Verify truth table, accessibility, and build**

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/components/DecisionDimensions.test.tsx src/components/ComparePanel.test.tsx src/utils/comparisonDiffs.test.ts && npm run build`

Expected: PASS; a significant but sub-threshold metric visibly fails practical meaning and release eligibility.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/dashboard/ui/src/components retrieval_observatory/dashboard/ui/src/api.ts CHANGELOG.md
git commit -m "feat: clarify comparison decisions"
```

### Task 7: Test Set Query Identity and Complete Provenance

**Files:**
- Modify: `retrieval_observatory/forge/types.py`
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Move: `retrieval_observatory/dashboard/ui/src/components/forge/DatasetDetail.tsx` to `retrieval_observatory/dashboard/ui/src/components/testsets/DatasetDetail.tsx`
- Create: `tests/unit/test_dashboard_testset_queries.py`

**Interfaces:**
- Consumes: unified Test Set summary and generated query metadata.
- Produces: `TestSetQueryProvenance` and paginated query envelope.

```python
class TestSetQueryProvenance(TypedDict):
    generation_method: str
    generator_version: str
    generation_model: str | None
    prompt_hash: str | None
    source_doc_ids: list[str]
    transformation: dict[str, object]
    label_class: str
    label_method: str
    judge_model: str | None
    validation_state: Literal['extractive', 'judge_validated', 'human_validated', 'rejected']
```

- [ ] **Step 1: Write positive and rejected-provenance tests**

```python
@pytest.mark.asyncio
async def test_testset_query_response_exposes_identity_and_provenance(client):
    body = (await client.get('/dbs/main/test-sets/set-1/queries', params={'limit': 10})).json()
    assert body['total'] == 1
    query = body['items'][0]
    assert query['query_id'] == 'temporal:doc-1:0'
    assert query['scenario_id'] == 'temporal:doc-1'
    assert query['provenance']['source_doc_ids'] == ['doc-1']
    assert query['provenance']['generator_version']

@pytest.mark.asyncio
async def test_missing_required_generation_method_is_rejected(store):
    with pytest.raises(ValueError, match='generation_method'):
        await store.save_test_set_queries('set-1', [{'query_id': 'q1', 'provenance': {}}])
```

- [ ] **Step 2: Run tests and confirm old list/optional provenance fails**

Run: `pytest -q tests/unit/test_dashboard_testset_queries.py tests/unit/test_testset_summary_contract.py`

Expected: FAIL because the endpoint returns a bare list and provenance fields are optional.

- [ ] **Step 3: Implement required storage/API contract and visible columns**

Use public `/dbs/{db_id}/test-sets/...` routes only; remove `/forge` aliases. The UI table columns are Query ID, Query, Scenario, Type, Difficulty, Source evidence, Generation, Labels, Validation. Add text/query-ID/scenario filters and retain server pagination. Unknown provenance is invalid at write time, not rendered as `unknown`.

- [ ] **Step 4: Verify Python/UI contracts and build**

Run: `pytest -q tests/unit/test_dashboard_testset_queries.py tests/unit/test_testset_summary_contract.py tests/unit/test_store_contract.py`

Run: `cd retrieval_observatory/dashboard/ui && npm test -- --run && npm run build`

Expected: all commands PASS; repetitive query text remains distinguishable by ID, scenario, and source evidence.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/forge retrieval_observatory/store retrieval_observatory/dashboard tests/unit/test_dashboard_testset_queries.py CHANGELOG.md
git commit -m "feat: expose test set query provenance"
```

### Task 8: Aggregate Evaluation-to-Production Matches

**Files:**
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Modify: `retrieval_observatory/dashboard/ui/src/components/RunQueryDetailPage.tsx`
- Test: `tests/unit/test_query_evidence_scope.py`
- Test: `retrieval_observatory/dashboard/ui/src/components/RunQueryDetailPage.test.tsx`

**Interfaces:**
- Consumes: query identity, topology fingerprint from Task 4, production trace evidence.
- Produces: `ProductionMatchSummary` grouped by `topology_id`, service, route, and match type.

```ts
export interface ProductionMatchGroup {
  topology_id: string
  service: string
  match_type: 'exact_query_id' | 'categorical'
  trace_count: number
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  status_counts: Record<string, number>
  suspected_failure_counts: Record<string, number>
  example_trace_ids: string[]
  evidence: EvidenceDescriptor
}
```

- [ ] **Step 1: Add bounded grouping tests**

```python
assert evidence['production_matches']['total_traces'] == 75
assert len(evidence['production_matches']['groups']) == 2
assert all(len(group['example_trace_ids']) <= 3 for group in evidence['production_matches']['groups'])
assert evidence['production_matches']['groups'][0]['evidence']['evidence_class'] in {'measured', 'heuristic'}
```

- [ ] **Step 2: Run the focused tests and confirm raw IDs dominate**

Run: `pytest -q tests/unit/test_query_evidence_scope.py`

Expected: FAIL because production matches are returned as a bounded but unaggregated trace list.

- [ ] **Step 3: Implement server-side grouping and UI disclosure**

Return group summaries ordered by exact match, then trace count descending. The query page shows group-level topology, service, latency, statuses, and evidence first; individual example IDs live in a collapsed disclosure and link to `#/production/<service>/traces?trace=<id>`.

- [ ] **Step 4: Verify API/UI behavior**

Run: `pytest -q tests/unit/test_query_evidence_scope.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/components/RunQueryDetailPage.test.tsx && npm run build`

Expected: PASS; no query page renders an unbounded list of production trace IDs.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/store retrieval_observatory/dashboard tests/unit/test_query_evidence_scope.py CHANGELOG.md
git commit -m "feat: summarize production query matches"
```

### Task 9: Live Browser Acceptance and Obsolete Surface Removal

**Files:**
- Modify: `tests/browser/test_dashboard_workflow.py`
- Modify: `retrieval_observatory/dashboard/ui/src/components/DemoQuickLinks.tsx`
- Delete after replacements exist: `retrieval_observatory/dashboard/ui/src/components/TraceLensWorkspace.tsx`
- Delete after replacements exist: `retrieval_observatory/dashboard/ui/src/components/ForgeWorkspace.tsx`
- Delete after moves exist: `retrieval_observatory/dashboard/ui/src/components/tracelens/`
- Delete after moves exist: `retrieval_observatory/dashboard/ui/src/components/forge/`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all Task 1–8 routes and components.
- Produces: live proof at 390, 768, and 1440 px; no deprecated public dashboard vocabulary.

- [ ] **Step 1: Add browser journeys before removing obsolete files**

```python
def test_dashboard_context_and_deep_links_survive_refresh(page: Page) -> None:
    page.goto(f'{BASE_URL}/#/production/demo/drift?db=demo&window=24h')
    expect(page.get_by_role('heading', name='Drift')).to_be_visible()
    page.reload()
    expect(page).to_have_url(re.compile(r'production/demo/drift.*db=demo.*window=24h'))
    expect(page.get_by_label('Database')).to_have_value('demo')

def test_architecture_search_and_testset_identity(page: Page) -> None:
    context = page.request.get(f'{BASE_URL}/demo/context').json()
    page.goto(f"{BASE_URL}/#/runs/{context['baseline_run_id']}/architecture?db={context['db_id']}")
    page.get_by_role('searchbox', name='Find trace').fill(context['sample_query_id'])
    expect(page.get_by_text(context['sample_query_id'], exact=False).first).to_be_visible()
    page.goto(f"{BASE_URL}/#/test-sets/{context['test_set_id']}?db={context['db_id']}")
    expect(page.get_by_role('columnheader', name='Query ID')).to_be_visible()
    expect(page.get_by_role('columnheader', name='Scenario')).to_be_visible()
```

- [ ] **Step 2: Run browser tests against a live demo and record failures**

Run server: `retobs demo --output /tmp/retobs-dashboard-core && retobs serve --db /tmp/retobs-dashboard-core/results.db --host 127.0.0.1 --port 4017`

Run tests: `RETOBS_E2E_URL=http://127.0.0.1:4017 pytest -q tests/browser/test_dashboard_workflow.py`

Expected before final cleanup: new journeys identify any missing routes, accessible names, or context fields.

- [ ] **Step 3: Remove obsolete names/routes/files and update demo links**

Delete superseded files only after imports point to `ProductionWorkspace`, `components/production`, and `components/testsets`. Remove `migrateLegacyPath`, `/tracelens`, `/forge`, and public TraceLens/Forge/Advisor/Benchmarks copy in touched dashboard code. Do not delete internal analysis modules required by another workstream until their replacements land.

- [ ] **Step 4: Run the complete workstream gate**

Run: `pytest -q tests/unit/test_dashboard_multi_db_api.py tests/unit/test_dashboard_trace_search.py tests/unit/test_dashboard_topology_variants.py tests/unit/test_dashboard_testset_queries.py tests/unit/test_query_evidence_scope.py tests/unit/test_pipeline_graph_contract_v2.py`

Run: `cd retrieval_observatory/dashboard/ui && npm test -- --run && npm run build`

Run: `RETOBS_E2E_URL=http://127.0.0.1:4017 pytest -q tests/browser/test_dashboard_workflow.py`

Run: `rg -n -i 'tracelens|forgeworkspace|benchmarksworkspace|migratelegacypath' retrieval_observatory/dashboard tests/browser`

Expected: Python, UI, build, and browser gates PASS; final `rg` returns no public legacy surface (an intentionally retained internal migration reference must be listed and justified in workstream 8, otherwise it is a failure).

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/dashboard tests/browser CHANGELOG.md
git commit -m "feat: complete scalable dashboard navigation"
```

## Workstream Acceptance Gate

- [ ] One database selection drives every primary workspace and survives refresh/back/forward.
- [ ] Every Production subview and time window has a canonical shareable URL.
- [ ] Architecture starts with topology variants and supports bounded trace search.
- [ ] Compare separates detectability, practical meaning, power, multiplicity, and release eligibility.
- [ ] Test Set rows visibly identify query, scenario, source evidence, generator/version, labels, and validation.
- [ ] Evaluation-to-production matches are grouped before individual trace disclosure.
- [ ] All list APIs are scoped, paginated, deterministic, and SQLite/PostgreSQL equivalent.
- [ ] Responsive/WCAG browser tests pass at 390, 768, and 1440 px.
- [ ] No removed public product name or legacy route remains in the dashboard.
