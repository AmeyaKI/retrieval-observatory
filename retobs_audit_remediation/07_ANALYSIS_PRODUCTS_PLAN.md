# Retrieval Analysis Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver eight retrieval-analysis products that make only evidence-supported claims, share cohorts and response semantics, and expose positive, partial, and unavailable states through APIs and dashboard routes.

**Architecture:** A shared analysis kernel evaluates versioned cohort predicates and wraps every result in one `AnalysisResult` evidence contract. Product modules remain independent pure analyzers over unified traces, metrics, qrels, manifests, telemetry counters, and health snapshots; thin FastAPI endpoints resolve scope and persistence. Saved cohorts, baselines, checks, and alerts reuse those analyzers rather than creating a second calculation path.

**Tech Stack:** Python 3.10+ dataclasses/typing, FastAPI, unified `RetrievalTrace` and `BaseStore`, SQLite/PostgreSQL, React 18, TypeScript 5.5, Recharts 2, Vitest, pytest, Playwright.

## Global Constraints

- Workstreams 2–6 are prerequisites: unified traces, safe telemetry counters, stable manifest topology, correct diagnostics, and global dashboard context must exist first.
- Analysis endpoint prefix is exactly `/dbs/{db_id}/analysis`; no global or legacy aliases are added.
- Every response uses `AnalysisResult[T]` with method/version, evidence class, sample, coverage, limitations, unavailable reason, and supporting IDs.
- Evidence classes are exactly `measured`, `statistical`, `replayed`, `heuristic`, `inferred`, and `unavailable`.
- A missing prerequisite returns HTTP 200 with `state="unavailable"`; malformed scope/filter input returns HTTP 422; missing database returns HTTP 404.
- “Partial” means the core calculation is valid for a disclosed subset; it must include a non-empty limitation and coverage below 1.0.
- All analyzers are deterministic pure functions; database and HTTP access remain outside product modules.
- Cohort predicates are declarative, versioned, validated, and evaluated identically in SQLite and PostgreSQL.
- Counterfactual branch claims require replayable evidence; observational estimates are labeled `inferred` or `heuristic`.
- Cross-operator score comparison is forbidden unless an explicit normalization method is recorded.
- External notification delivery is out of scope; alerts are durable local events.
- Update `CHANGELOG.md` under `[Unreleased]` for each shipped product.
- Every product task must add positive, partial, and unavailable tests before implementation.

---

## Target File Map

**Create shared kernel**

- `retrieval_observatory/analysis/contracts.py` — generic result, evidence, scope, page, and state types.
- `retrieval_observatory/analysis/cohorts.py` — predicate schema, validation, and pure evaluation.
- `retrieval_observatory/analysis/service.py` — scope resolution and analyzer orchestration.
- `retrieval_observatory/analysis/__init__.py` — intentional public exports.
- `retrieval_observatory/dashboard/analysis_api.py` — analysis router only.
- `retrieval_observatory/dashboard/ui/src/analysis/contracts.ts` — TypeScript mirrors.
- `retrieval_observatory/dashboard/ui/src/analysis/AnalysisState.tsx` — common ready/partial/unavailable renderer.
- `tests/fixtures/analysis_fixtures.py` — deterministic unified-trace, qrel, manifest, counter, judgment, and snapshot factories shared by product contract tests.
- `tests/unit/test_analysis_contracts.py`, `test_cohorts.py`, `test_analysis_api_contract.py`.

**Create product modules and UI**

- `analysis/gates.py` and `ui/src/analysis/GateAnalysisPage.tsx`.
- `analysis/branches.py` and `ui/src/analysis/BranchContributionPage.tsx`.
- `analysis/scores.py` and `ui/src/analysis/ScoreAnalysisPage.tsx`.
- `analysis/latency.py` and `ui/src/analysis/LatencyAnalysisPage.tsx`.
- `analysis/corpus_health.py` and `ui/src/analysis/CorpusHealthPage.tsx`.
- `analysis/ground_truth.py` and `ui/src/analysis/GroundTruthHealthPage.tsx`.
- `analysis/instrumentation.py` and `ui/src/analysis/InstrumentationHealthPage.tsx`.
- `analysis/checks.py` and `ui/src/analysis/CohortsChecksPage.tsx`.

**Modify**

- `retrieval_observatory/dashboard/api.py` — include `analysis_router`.
- `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py` — cohort, health snapshot, judgment, baseline, check, and alert persistence.
- `retrieval_observatory/dashboard/ui/src/api.ts` — analysis fetch client.
- `retrieval_observatory/dashboard/ui/src/components/RunPageLayout.tsx`, `ProductionWorkspace.tsx`, and `routing.ts` — analysis routes.
- `tests/browser/test_dashboard_workflow.py` and `CHANGELOG.md`.

### Task 1: Shared Evidence, Scope, and Analysis Result Contract

**Files:**
- Create: `retrieval_observatory/analysis/contracts.py`
- Create: `retrieval_observatory/analysis/__init__.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/contracts.ts`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/AnalysisState.tsx`
- Create: `tests/fixtures/analysis_fixtures.py`
- Create: `tests/unit/test_analysis_contracts.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/AnalysisState.test.tsx`

**Interfaces:**
- Consumes: stable IDs and evidence vocabulary from `00_DESIGN.md`.
- Produces:

```python
AnalysisState = Literal['ready', 'partial', 'unavailable']
EvidenceClass = Literal['measured', 'statistical', 'replayed', 'heuristic', 'inferred', 'unavailable']

@dataclass(frozen=True)
class AnalysisScope:
    db_id: str
    service_id: str | None = None
    run_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    cohort_id: str | None = None

@dataclass(frozen=True)
class EvidenceDescriptor:
    evidence_class: EvidenceClass
    method_id: str
    method_version: str
    sample_size: int
    population_size: int
    coverage: float
    thresholds: dict[str, float | int | str]
    limitations: tuple[str, ...]
    supporting_trace_ids: tuple[str, ...] = ()
    supporting_query_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class AnalysisResult(Generic[T]):
    state: AnalysisState
    scope: AnalysisScope
    evidence: EvidenceDescriptor
    data: T | None
    unavailable_reason: str | None
```

The fixture module produces the exact named inputs used later:

```python
def make_trace(*, trace_id: str = 't1', run_id: str | None = 'r1', service_id: str = 'search',
               query_id: str = 'q1', spans: tuple[OperatorSpan, ...] = (),
               metadata: dict[str, object] | None = None) -> RetrievalTrace: ...
def source_span(op_id: str, outputs: list[Candidate]) -> OperatorSpan: ...
def gate_span(op_id: str, parent_ids: list[str], route: str, selected: bool = True) -> OperatorSpan: ...
def fuse_span(op_id: str, parent_ids: list[str], input_groups: dict[str, list[Candidate]], outputs: list[Candidate]) -> OperatorSpan: ...
def candidate(doc_id: str, rank: int, score: float, origins: tuple[str, ...] = ()) -> Candidate: ...
def analysis_scope(**overrides: object) -> AnalysisScope: ...
def evidence_descriptor(**overrides: object) -> EvidenceDescriptor: ...
```

Each later test module defines its named fixture (`gated_traces`, `hybrid_traces`, `parallel_traces`, `scored_traces`, `snapshot`, `judgments`, `manifest`, and counters) by composing these factories in that test file. No test may load the demo database or depend on wall-clock time.

- [ ] **Step 1: Write invariant and UI-state tests**

```python
def test_ready_result_requires_data_and_nonzero_sample():
    with pytest.raises(ValueError, match='ready analysis requires data'):
        AnalysisResult(state='ready', scope=analysis_scope(), evidence=evidence_descriptor(sample_size=0, population_size=0), data=None, unavailable_reason=None)

def test_partial_result_requires_limitations_and_incomplete_coverage():
    with pytest.raises(ValueError, match='partial analysis requires'):
        AnalysisResult(state='partial', scope=analysis_scope(), evidence=evidence_descriptor(coverage=1.0, limitations=()), data={}, unavailable_reason=None)

def test_unavailable_result_has_no_data_and_explicit_reason():
    result = unavailable(analysis_scope(), method_id='gates', reason='No GATE spans were captured.')
    assert result.data is None
    assert result.evidence.evidence_class == 'unavailable'
```

```tsx
it.each(['ready', 'partial', 'unavailable'] as const)('renders factual %s state', (state) => {
  const result: AnalysisResult<{ count: number }> = {
    state,
    scope: { db_id: 'main', service: null, run_id: 'r1', since: null, until: null, cohort_id: null },
    evidence: {
      evidence_class: state === 'unavailable' ? 'unavailable' : 'measured',
      method_id: 'contract-test', method_version: '1', sample_size: state === 'unavailable' ? 0 : 2,
      population_size: 2, coverage: state === 'partial' ? 0.5 : state === 'ready' ? 1 : 0,
      thresholds: {}, limitations: state === 'partial' ? ['one trace omitted'] : [],
      supporting_trace_ids: [], supporting_query_ids: [],
    },
    data: state === 'unavailable' ? null : { count: 2 },
    unavailable_reason: state === 'unavailable' ? 'No compatible evidence was captured.' : null,
  }
  render(<AnalysisState result={result}>{() => <div>analysis</div>}</AnalysisState>)
  expect(screen.getByRole('status')).toHaveAttribute('data-state', state)
})
```

- [ ] **Step 2: Run tests and confirm shared types are absent**

Run: `pytest -q tests/unit/test_analysis_contracts.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/AnalysisState.test.tsx`

Expected: both commands FAIL because the shared contracts do not exist.

- [ ] **Step 3: Implement validated constructors and exact TypeScript mirror**

Validate coverage in `[0,1]`, non-negative population/sample, sample not above population, and state invariants in `__post_init__`. `AnalysisState` always renders method/version/sample/coverage, limitations, and unavailable reason; it does not render children when unavailable.

- [ ] **Step 4: Run contract tests**

Run: `pytest -q tests/unit/test_analysis_contracts.py && cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/AnalysisState.test.tsx`

Expected: PASS for Python invariants and all three UI states.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis retrieval_observatory/dashboard/ui/src/analysis tests/fixtures/analysis_fixtures.py tests/unit/test_analysis_contracts.py CHANGELOG.md
git commit -m "feat: define shared analysis evidence contract"
```

### Task 2: Versioned Cohort Predicates and Shared Analysis Router

**Files:**
- Create: `retrieval_observatory/analysis/cohorts.py`
- Create: `retrieval_observatory/analysis/service.py`
- Create: `retrieval_observatory/dashboard/analysis_api.py`
- Create: `tests/unit/test_cohorts.py`
- Create: `tests/unit/test_analysis_api_contract.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py`

**Interfaces:**
- Consumes: `AnalysisScope`, unified traces, run queries, metrics.
- Produces:

```python
PredicateOperator = Literal['eq', 'ne', 'in', 'gte', 'lte', 'contains', 'exists']

@dataclass(frozen=True)
class CohortClause:
    field: str
    operator: PredicateOperator
    value: str | float | int | bool | tuple[str, ...] | None

@dataclass(frozen=True)
class CohortDefinition:
    cohort_id: str
    name: str
    version: int
    clauses: tuple[CohortClause, ...]
    conjunction: Literal['all', 'any'] = 'all'

def validate_cohort(definition: CohortDefinition) -> None: ...
def matches_cohort(record: Mapping[str, object], definition: CohortDefinition) -> bool: ...
```

Allowed fields are `query.id`, `query.text`, `query.metadata.<key>`, `trace.status`, `trace.service`, `trace.pipeline_id`, `trace.topology_id`, `trace.total_latency_ms`, `trace.metadata.<key>`, `diagnostic.label`, and `route.value`. Arbitrary object traversal is forbidden.

- [ ] **Step 1: Write validation, parity, and unavailable API tests**

```python
def test_cohort_rejects_unknown_field_and_operator():
    with pytest.raises(ValueError, match='field is not allowed'):
        validate_cohort(CohortDefinition('c1', 'bad', 1, (CohortClause('__class__', 'eq', 'x'),)))

def test_cohort_all_clauses_match_nested_metadata():
    cohort = CohortDefinition('hard-errors', 'Hard errors', 1, (
        CohortClause('trace.status', 'eq', 'ERROR'),
        CohortClause('query.metadata.tenant', 'in', ('legal', 'finance')),
    ))
    assert matches_cohort(record, cohort) is True

@pytest.mark.asyncio
async def test_analysis_missing_evidence_is_200_unavailable(client):
    response = await client.get('/dbs/main/analysis/gates', params={'run_id': 'empty'})
    assert response.status_code == 200
    assert response.json()['state'] == 'unavailable'
```

- [ ] **Step 2: Run tests and verify no shared cohort path exists**

Run: `pytest -q tests/unit/test_cohorts.py tests/unit/test_analysis_api_contract.py`

Expected: FAIL because cohort types, persistence, and analysis router are absent.

- [ ] **Step 3: Implement pure predicate evaluation, persistence, and router dependencies**

Add `save_cohort`, `get_cohort`, `list_cohorts`, `delete_cohort` to `BaseStore` and both stores. Persist canonical JSON plus version; reject overwrite unless incoming version is exactly current+1. `analysis_api.py` defines `resolve_scope(db_id, service, run_id, since, until, cohort_id)` and loads the cohort once. Include its router from `create_app`; product endpoints register with this router in later tasks.

- [ ] **Step 4: Run cohort, API, and store parity tests**

Run: `pytest -q tests/unit/test_cohorts.py tests/unit/test_analysis_api_contract.py tests/unit/test_store_contract.py tests/unit/test_store_postgres.py`

Expected: PASS; identical records match identically and invalid fields return 422.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis retrieval_observatory/dashboard retrieval_observatory/store tests/unit/test_cohorts.py tests/unit/test_analysis_api_contract.py CHANGELOG.md
git commit -m "feat: add shared cohort analysis scope"
```

### Task 3: Router and Gate Analysis

**Files:**
- Create: `retrieval_observatory/analysis/gates.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/GateAnalysisPage.tsx`
- Create: `tests/unit/test_gate_analysis.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/GateAnalysisPage.test.tsx`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: GATE spans, `gate_values`, status, qrels/metrics, cohort-filtered traces.
- Produces: `analyze_gates(traces, qrels, route_labels, scope) -> AnalysisResult[GateAnalysis]` with gate traffic, decision counts, route quality/coverage, skipped-branch outcomes, route drift, and optional confusion matrix.

- [ ] **Step 1: Write positive, partial, and unavailable tests**

```python
def test_gate_analysis_builds_labeled_confusion_and_route_quality():
    result = analyze_gates(gated_traces, qrels, {'q1': 'legal', 'q2': 'general'}, scope)
    assert result.state == 'ready'
    assert result.data.confusion['legal']['legal'] == 1
    assert result.data.routes['legal'].quality['recall@10'] == pytest.approx(1.0)

def test_gate_analysis_without_route_labels_is_partial():
    result = analyze_gates(gated_traces, qrels, {}, scope)
    assert result.state == 'partial'
    assert result.data.confusion is None
    assert 'route labels' in ' '.join(result.evidence.limitations)

def test_gate_analysis_without_gate_spans_is_unavailable():
    result = analyze_gates(linear_traces, {}, {}, scope)
    assert result.state == 'unavailable'
    assert result.unavailable_reason == 'No GATE operator spans were captured in this scope.'
```

- [ ] **Step 2: Run tests and confirm analyzer is absent**

Run: `pytest -q tests/unit/test_gate_analysis.py`

Expected: FAIL importing `retrieval_observatory.analysis.gates`.

- [ ] **Step 3: Implement pure analysis, endpoint, and page**

Use measured gate decisions; route quality requires qrels and is statistical when aggregated; confusion requires explicit expected route labels and must not infer them from outcomes. UI sections: Traffic, Route decisions, Confusion, Per-route quality/coverage, Skipped branches, Route drift. Wrap all with `AnalysisState`.

- [ ] **Step 4: Run product and UI tests**

Run: `pytest -q tests/unit/test_gate_analysis.py tests/unit/test_analysis_api_contract.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/GateAnalysisPage.test.tsx && npm run build`

Expected: positive, partial, and unavailable states PASS; confusion is absent without route labels.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/gates.py retrieval_observatory/dashboard tests/unit/test_gate_analysis.py CHANGELOG.md
git commit -m "feat: add gate and router analysis"
```

### Task 4: Branch Contribution Analysis

**Files:**
- Create: `retrieval_observatory/analysis/branches.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/BranchContributionPage.tsx`
- Create: `tests/unit/test_branch_analysis.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/BranchContributionPage.test.tsx`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: source/fusion spans, candidate `origin_op_ids`, qrels, replay policies.
- Produces: overlap/unique candidate counts, relevant-document contribution, measured fusion gain, and replayed or observational removal estimates.

- [ ] **Step 1: Write three evidence-state tests**

```python
def test_branch_analysis_measures_overlap_unique_and_relevant_contribution():
    result = analyze_branches(hybrid_traces, qrels, scope)
    assert result.state == 'ready'
    assert result.data.pairs[0].overlap_count == 1
    assert result.data.branches['dense'].unique_relevant_count == 1

def test_nonreplayable_branch_removal_is_partial_and_inferred():
    result = analyze_branches(nonreplayable_traces, qrels, scope)
    assert result.state == 'partial'
    assert result.data.removal_estimates[0].evidence_class == 'inferred'

def test_branch_analysis_without_origin_or_fusion_is_unavailable():
    assert analyze_branches(linear_traces, qrels, scope).state == 'unavailable'
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_branch_analysis.py`

Expected: FAIL because branch analyzer is absent.

- [ ] **Step 3: Implement candidate-set algebra and factual copy**

Compute overlap from stable doc IDs at branch outputs, unique relevant contribution from qrels, and fusion gain as final relevant set minus union-at-cutoff semantics declared in the response. Use `replayed` only when replay policy and descendants support removal; otherwise label observational estimates `inferred` and explain confounding. UI reuses `ProvenanceSankey` and accessible tables.

- [ ] **Step 4: Verify product/UI**

Run: `pytest -q tests/unit/test_branch_analysis.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/BranchContributionPage.test.tsx && npm run build`

Expected: all three states PASS; no observational removal is labeled counterfactual.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/branches.py retrieval_observatory/dashboard tests/unit/test_branch_analysis.py CHANGELOG.md
git commit -m "feat: add branch contribution analysis"
```

### Task 5: Score Calibration and Threshold Sensitivity

**Files:**
- Create: `retrieval_observatory/analysis/scores.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/ScoreAnalysisPage.tsx`
- Create: `tests/unit/test_score_analysis.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/ScoreAnalysisPage.test.tsx`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: per-operator candidate scores, qrels, declared score semantics/normalization.
- Produces: distributions, reliability bins, AUROC where both classes exist, normalization diagnostics, and threshold sensitivity points.

- [ ] **Step 1: Write ready/partial/unavailable tests**

```python
def test_labeled_scores_produce_calibration_and_threshold_curve():
    result = analyze_scores(scored_traces, qrels, {'dense': {'normalization': 'cosine'}}, scope)
    assert result.state == 'ready'
    assert len(result.data.operators['dense'].threshold_curve) >= 2
    assert result.data.operators['dense'].reliability_bins[0].count > 0

def test_unlabeled_scores_are_partial_distribution_only():
    result = analyze_scores(scored_traces, {}, {'dense': {'normalization': 'cosine'}}, scope)
    assert result.state == 'partial'
    assert result.data.operators['dense'].calibration is None

def test_scores_without_declared_semantics_are_unavailable_for_cross_operator_view():
    result = analyze_scores(scored_traces, qrels, {}, scope, compare_operators=True)
    assert result.state == 'unavailable'
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_score_analysis.py`

Expected: FAIL because score analyzer is absent.

- [ ] **Step 3: Implement deterministic bins and threshold calculations**

Use 10 equal-width bins within each declared normalized score domain; include bin boundaries and counts. Threshold points are unique observed scores capped to 100 quantile-selected points and include retained count, relevant retained, precision, recall, and estimated latency only when measured. UI uses `ChartFrame`/Recharts and never overlays incompatible operator scales.

- [ ] **Step 4: Verify analysis/UI**

Run: `pytest -q tests/unit/test_score_analysis.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/ScoreAnalysisPage.test.tsx && npm run build`

Expected: PASS; unlabeled data shows distributions but suppresses calibration.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/scores.py retrieval_observatory/dashboard tests/unit/test_score_analysis.py CHANGELOG.md
git commit -m "feat: add score and threshold analysis"
```

### Task 6: Latency Critical-Path Analysis

**Files:**
- Create: `retrieval_observatory/analysis/latency.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/LatencyAnalysisPage.tsx`
- Create: `tests/unit/test_latency_analysis.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/LatencyAnalysisPage.test.tsx`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: trace wall clock, critical path, operator sum, DAG parents, optional `timing_components` metadata.
- Produces: p50/p95/p99 across timing views, operator criticality, parallelism ratio, path variants, and optional queue/network/model/storage components.

- [ ] **Step 1: Write three state tests**

```python
def test_latency_analysis_separates_wall_critical_and_operator_sum():
    result = analyze_latency(parallel_traces, scope)
    assert result.state == 'ready'
    assert result.data.percentiles['wall_clock_ms']['p95'] == 120.0
    assert result.data.percentiles['operator_sum_ms']['p95'] > result.data.percentiles['critical_path_ms']['p95']

def test_missing_component_breakdown_is_partial_not_invented():
    result = analyze_latency(parallel_traces_without_components, scope)
    assert result.state == 'partial'
    assert result.data.component_percentiles is None

def test_missing_valid_timing_is_unavailable():
    assert analyze_latency(traces_without_timing, scope).state == 'unavailable'
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_latency_analysis.py`

Expected: FAIL because aggregate latency analysis is absent.

- [ ] **Step 3: Implement path aggregation and component gating**

Use nearest-rank percentiles with documented method ID `latency-critical-path/1`. An operator is critical when it appears on a longest path; report frequency and latency contribution. Component attribution requires standardized non-negative components whose sum is within 5% of wall clock; invalid component traces are excluded and reduce coverage.

- [ ] **Step 4: Verify analysis/UI**

Run: `pytest -q tests/unit/test_latency_analysis.py tests/unit/test_tracing_improvements.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/LatencyAnalysisPage.test.tsx && npm run build`

Expected: PASS; queue/network/model/storage charts are absent unless captured and validated.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/latency.py retrieval_observatory/dashboard tests/unit/test_latency_analysis.py CHANGELOG.md
git commit -m "feat: add critical path latency analysis"
```

### Task 7: Corpus and Index Health

**Files:**
- Create: `retrieval_observatory/analysis/corpus_health.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/CorpusHealthPage.tsx`
- Create: `tests/unit/test_corpus_health.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/CorpusHealthPage.test.tsx`
- Modify: `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: corpus/index snapshots captured under workstream 2/4: versions, document/chunk IDs, timestamps, duplicates, tenant/shard, ACL/filter counts, qrel coverage.
- Produces: freshness/version coverage, duplicate groups, chunk coverage, missing qrels, ACL/filter effects, and shard/selectivity summaries.

- [ ] **Step 1: Write positive, partial, and unavailable tests**

```python
def test_corpus_health_reports_versions_freshness_duplicates_and_selectivity():
    result = analyze_corpus_health(snapshot, traces, qrels, scope)
    assert result.state == 'ready'
    assert result.data.index_versions['idx-2026-07'].trace_share == pytest.approx(1.0)
    assert result.data.duplicate_document_groups == 1

def test_missing_acl_and_shard_capture_is_partial():
    result = analyze_corpus_health(snapshot_without_operational_fields, traces, qrels, scope)
    assert result.state == 'partial'
    assert result.data.acl_effects is None

def test_no_corpus_snapshot_is_unavailable():
    assert analyze_corpus_health(None, traces, qrels, scope).state == 'unavailable'
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_corpus_health.py`

Expected: FAIL because snapshots/analyzer are absent.

- [ ] **Step 3: Implement snapshot persistence and health calculations**

Add `save_corpus_snapshot` and `get_corpus_snapshot(corpus_id, version)` to stores. Freshness reports age distribution from source timestamps; duplicates require content hashes; chunk coverage requires parent document IDs; ACL/filter effects require before/after candidate counts; shard/selectivity requires captured shard and scanned/matched counts. Each missing optional family produces a named limitation, never a zero.

- [ ] **Step 4: Verify analyzer, stores, UI**

Run: `pytest -q tests/unit/test_corpus_health.py tests/unit/test_store_contract.py tests/unit/test_store_postgres.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/CorpusHealthPage.test.tsx && npm run build`

Expected: PASS; missing operational fields render unavailable subsections rather than healthy zeros.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/corpus_health.py retrieval_observatory/store retrieval_observatory/dashboard tests/unit/test_corpus_health.py CHANGELOG.md
git commit -m "feat: add corpus and index health"
```

### Task 8: Ground-Truth Health and Durable Label Audit Queue

**Files:**
- Create: `retrieval_observatory/analysis/ground_truth.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/GroundTruthHealthPage.tsx`
- Create: `tests/unit/test_ground_truth_health.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/GroundTruthHealthPage.test.tsx`
- Modify: `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: qrels with provenance/version/assessor, retrieved candidates, Test Set validation state.
- Produces: judgment coverage, assessor disagreement, unjudged result rate, provenance/version drift, and audit items with state `open|in_review|resolved|rejected`.

- [ ] **Step 1: Write health and queue state tests**

```python
def test_ground_truth_health_reports_disagreement_and_unjudged_rate():
    result = analyze_ground_truth(judgments, traces, scope)
    assert result.state == 'ready'
    assert result.data.assessor_disagreement.query_count == 1
    assert result.data.unjudged_result_rate == pytest.approx(0.5)

def test_single_assessor_is_partial():
    result = analyze_ground_truth(single_assessor_judgments, traces, scope)
    assert result.state == 'partial'
    assert result.data.assessor_disagreement is None

def test_no_judgments_is_unavailable():
    assert analyze_ground_truth([], traces, scope).state == 'unavailable'

@pytest.mark.asyncio
async def test_audit_item_transition_is_version_checked(store):
    item = await store.create_label_audit_item(query_id='q1', doc_id='d1', reason='assessor_disagreement')
    updated = await store.update_label_audit_item(item.audit_id, expected_version=1, state='in_review')
    assert updated.version == 2
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_ground_truth_health.py`

Expected: FAIL because judgment provenance and audit persistence are absent.

- [ ] **Step 3: Implement append-only judgments and optimistic queue updates**

Do not overwrite judgment history. A judgment key contains dataset/query/doc/assessor/version; active qrels derive from the selected label version. Audit queue updates require expected version and return HTTP 409 on conflict. UI exposes filters, provenance, disagreement evidence, and explicit resolution notes.

- [ ] **Step 4: Verify product/store/UI**

Run: `pytest -q tests/unit/test_ground_truth_health.py tests/unit/test_store_contract.py tests/unit/test_store_postgres.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/GroundTruthHealthPage.test.tsx && npm run build`

Expected: PASS; single-assessor data is partial and concurrent audit updates conflict safely.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/ground_truth.py retrieval_observatory/store retrieval_observatory/dashboard tests/unit/test_ground_truth_health.py CHANGELOG.md
git commit -m "feat: add ground truth health and audit queue"
```

### Task 9: Instrumentation Health

**Files:**
- Create: `retrieval_observatory/analysis/instrumentation.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/InstrumentationHealthPage.tsx`
- Create: `tests/unit/test_instrumentation_health.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/InstrumentationHealthPage.test.tsx`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: integration manifest expected operators/topologies, traces, workstream 3 exporter counters, sampling/candidate capture metadata.
- Produces: expected/observed coverage, stable identity/topology, sampling, drops, serialization failures, truncation, queue/export health.

- [ ] **Step 1: Write healthy, degraded, and unavailable tests**

```python
def test_instrumentation_health_ready_when_manifest_and_capture_agree():
    result = analyze_instrumentation(manifest, traces, healthy_counters, scope)
    assert result.state == 'ready'
    assert result.data.operator_coverage == pytest.approx(1.0)
    assert result.data.dropped_traces == 0

def test_drops_and_missing_operator_produce_partial_health():
    result = analyze_instrumentation(manifest, incomplete_traces, dropping_counters, scope)
    assert result.state == 'partial'
    assert result.data.missing_operator_ids == ['rerank']
    assert result.data.dropped_traces == 3

def test_missing_manifest_and_counters_is_unavailable():
    assert analyze_instrumentation(None, traces, None, scope).state == 'unavailable'
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_instrumentation_health.py`

Expected: FAIL because health analyzer is absent.

- [ ] **Step 3: Implement manifest comparison and capture-health rules**

Stable identity compares operator ID/type/parents across representative scenarios. Topology coverage uses expected variants from verification scenarios. Candidate coverage counts fired retrieval operators with captured inputs/outputs. Overall state is partial for any drops, serialization failures, unstable identities, missing required operators, undisclosed sampling, or incomplete required candidate capture. UI links supporting traces and remediation commands.

- [ ] **Step 4: Verify product/UI**

Run: `pytest -q tests/unit/test_instrumentation_health.py tests/unit/test_verify_checks.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/InstrumentationHealthPage.test.tsx && npm run build`

Expected: PASS; health never reports ready when exporter drops or expected topology is missing.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/instrumentation.py retrieval_observatory/dashboard tests/unit/test_instrumentation_health.py CHANGELOG.md
git commit -m "feat: add instrumentation health analysis"
```

### Task 10: Saved Cohorts, Baselines, Checks, and Local Alerts

**Files:**
- Create: `retrieval_observatory/analysis/checks.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/CohortsChecksPage.tsx`
- Create: `tests/unit/test_analysis_checks.py`
- Create: `retrieval_observatory/dashboard/ui/src/analysis/CohortsChecksPage.test.tsx`
- Modify: `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py`
- Modify: `retrieval_observatory/runner/scheduler.py`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`, `dashboard/ui/src/api.ts`

**Interfaces:**
- Consumes: versioned cohorts and every product analyzer through `AnalysisService.run_product(product_id, scope)`.
- Produces: pinned baseline, check definition/result, and local alert event records.

```python
@dataclass(frozen=True)
class RegressionCheck:
    check_id: str
    name: str
    product_id: Literal['gates','branches','scores','latency','corpus-health','ground-truth','instrumentation']
    cohort_id: str | None
    baseline_id: str
    schedule: str | None
    assertion: CheckAssertion
    enabled: bool

@dataclass(frozen=True)
class CheckAssertion:
    json_path: str
    operator: Literal['gte','lte','increase_lte','decrease_lte','state_is']
    value: float | str
```

- [ ] **Step 1: Write ready/partial/unavailable check tests**

```python
@pytest.mark.asyncio
async def test_check_persists_pass_and_failure_alert(store, service):
    passed = await run_check(latency_check, current_scope, service, store)
    assert passed.state == 'passed'
    failed = await run_check(replace(latency_check, assertion=CheckAssertion('data.percentiles.wall_clock_ms.p95', 'lte', 50.0)), current_scope, service, store)
    assert failed.state == 'failed'
    assert (await store.list_alert_events(check_id=latency_check.check_id))[0].result_id == failed.result_id

@pytest.mark.asyncio
async def test_partial_analysis_makes_check_indeterminate(store, service):
    result = await run_check(component_latency_check, partial_scope, service, store)
    assert result.state == 'indeterminate'

@pytest.mark.asyncio
async def test_unavailable_analysis_makes_check_unavailable(store, service):
    result = await run_check(gate_check, no_gate_scope, service, store)
    assert result.state == 'unavailable'
```

- [ ] **Step 2: Run failing tests**

Run: `pytest -q tests/unit/test_analysis_checks.py`

Expected: FAIL because baselines/checks/alerts are absent.

- [ ] **Step 3: Implement durable records and scheduler integration**

Pin baselines as immutable analysis-result snapshots with scope and evidence. JSON paths are validated against an allowlist published by each product; arbitrary evaluation is forbidden. A partial result is indeterminate unless the asserted path is explicitly complete. Persist every run result and create one local alert event per transition into failed, not on every repeated failure. `schedule=None` is manual; non-null schedules use the existing local scheduler and support minute/hour/day intervals defined by its contract.

- [ ] **Step 4: Verify persistence, scheduler, and UI**

Run: `pytest -q tests/unit/test_analysis_checks.py tests/unit/test_store_contract.py tests/unit/test_store_postgres.py`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/analysis/CohortsChecksPage.test.tsx && npm run build`

Expected: PASS; failed transitions create durable local alerts, while partial/unavailable evidence cannot create false regression failures.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/analysis/checks.py retrieval_observatory/store retrieval_observatory/runner/scheduler.py retrieval_observatory/dashboard tests/unit/test_analysis_checks.py CHANGELOG.md
git commit -m "feat: add saved cohorts and regression checks"
```

### Task 11: Analysis Navigation, Cohort Injection, and Live Acceptance

**Files:**
- Modify: `retrieval_observatory/dashboard/ui/src/components/RunPageLayout.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/ProductionWorkspace.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/GlobalContextBar.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/routing.ts`, `routing.test.ts`
- Modify: `tests/browser/test_dashboard_workflow.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all seven analysis endpoint families plus cohorts/checks from Tasks 1–10.
- Produces canonical routes:
  - `runs/:runId/analysis/:product`
  - `production/:service/analysis/:product`
  - `analysis/cohorts-checks`

- [ ] **Step 1: Add route and browser acceptance tests**

```ts
it('deep-links every analysis product with a cohort', () => {
  const match = ANALYSIS_ROUTES.match('runs/r1/analysis/gates?db=main&cohort=hard')
  expect(match?.params).toEqual({ runId: 'r1', product: 'gates' })
  expect(match?.query.cohort).toBe('hard')
})
```

```python
@pytest.mark.parametrize('product', [
    'gates', 'branches', 'scores', 'latency', 'corpus-health', 'ground-truth', 'instrumentation',
])
def test_analysis_pages_have_evidence_and_no_console_errors(page: Page, product: str) -> None:
    context = page.request.get(f'{BASE_URL}/demo/context').json()
    errors = []
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.goto(f"{BASE_URL}/#/runs/{context['baseline_run_id']}/analysis/{product}?db={context['db_id']}")
    expect(page.get_by_text('Evidence', exact=False).first).to_be_visible()
    assert errors == []
```

- [ ] **Step 2: Run tests against the enhanced demo fixture**

Run server: `retobs demo --output /tmp/retobs-analysis-demo && retobs serve --db /tmp/retobs-analysis-demo/results.db --host 127.0.0.1 --port 4018`

Run: `cd retrieval_observatory/dashboard/ui && npx vitest run src/routing.test.ts`

Run: `RETOBS_E2E_URL=http://127.0.0.1:4018 pytest -q tests/browser/test_dashboard_workflow.py`

Expected before navigation implementation: route/browser tests FAIL because analysis pages are not mounted.

- [ ] **Step 3: Mount pages and inject cohort scope uniformly**

Add product navigation under run and production context; do not add eight primary rail items. `GlobalContextBar` lists saved cohorts and updates the global URL. Every analysis fetch receives the same cohort ID, run/service, and time window. Product pages retain a shareable URL and use `AnalysisState` for every response.

- [ ] **Step 4: Run complete workstream gate**

Run: `pytest -q tests/unit/test_analysis_contracts.py tests/unit/test_cohorts.py tests/unit/test_analysis_api_contract.py tests/unit/test_gate_analysis.py tests/unit/test_branch_analysis.py tests/unit/test_score_analysis.py tests/unit/test_latency_analysis.py tests/unit/test_corpus_health.py tests/unit/test_ground_truth_health.py tests/unit/test_instrumentation_health.py tests/unit/test_analysis_checks.py`

Run: `cd retrieval_observatory/dashboard/ui && npm test -- --run && npm run build`

Run: `RETOBS_E2E_URL=http://127.0.0.1:4018 pytest -q tests/browser/test_dashboard_workflow.py`

Expected: all Python, UI, build, and browser tests PASS; every product demonstrates ready plus partial or unavailable live state without console/API errors.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/dashboard tests/browser CHANGELOG.md
git commit -m "feat: expose retrieval analysis products"
```

## Product Evidence Matrix

| Product | Ready evidence | Partial trigger | Unavailable trigger |
|---|---|---|---|
| Gates | GATE spans + explicit route labels + qrels | GATE spans but missing labels or qrels | no GATE spans |
| Branches | stable branch origins + fusion + qrels + replayability for counterfactuals | observational-only removal or incomplete labels | no branch/fusion lineage |
| Scores | scores + semantics + both relevance classes | distributions without labels or single class | missing scores; incompatible comparison requested |
| Latency | valid trace timing and DAG | missing optional component capture | no valid timing |
| Corpus/index | versioned corpus snapshot plus trace identity | missing optional ACL/shard/chunk fields | no corpus snapshot |
| Ground truth | versioned multi-assessor judgments + retrieval results | single assessor or incomplete provenance | no judgments |
| Instrumentation | manifest + representative traces + counters | drops, missing operators, unstable identity, incomplete coverage | missing manifest and health counters |
| Checks/alerts | ready product result and compatible pinned baseline | partial asserted data | unavailable product result |

## Workstream Acceptance Gate

- [ ] One shared evidence/result contract is used by every product API and UI.
- [ ] One cohort predicate implementation scopes every product identically across stores.
- [ ] Each of the eight products has positive, partial, and unavailable contract tests.
- [ ] No product substitutes zero for unavailable evidence.
- [ ] No confusion/calibration/quality claim appears without labels.
- [ ] No timing-component attribution appears without captured, validated components.
- [ ] No counterfactual branch claim appears without replayable evidence.
- [ ] Corpus, judgment, cohort, baseline, check, and alert persistence has SQLite/PostgreSQL parity.
- [ ] Saved checks cannot turn partial or unavailable evidence into a false failure.
- [ ] Routes are shareable, cohort-aware, responsive, accessible, and free of console/API errors.
