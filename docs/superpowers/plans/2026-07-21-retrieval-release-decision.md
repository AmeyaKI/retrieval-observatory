# Retrieval Release Evidence and Candidate Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `retobs compare` emit a local, auditable `PASS` / `HOLD` / `BLOCK` / `FAIL` decision for a retrieval change, then let an engineer inspect evidence-qualified candidate movement through the affected query's retrieval DAG.

**Architecture:** Preserve RetObs's existing run manifests, metric rows, `RetrievalTrace`, candidate transitions, candidate-flow UI, and reviewed integration workflow. Add a release-policy/evidence layer above them; evolve the trace candidate model from document-ID-based before/after lists into a versioned, identity-preserving candidate-lineage DAG; derive a query-scoped lineage read model from persisted traces; and make the dashboard flow from a release decision to a static lineage graph and selected-candidate passport. Keep raw source content local and redaction-aware.

**Tech Stack:** Python 3.10+, dataclasses, Pydantic v2, PyYAML, asyncio, SQLite/PostgreSQL, Typer, FastAPI, React 18, TypeScript, Vite, Vitest, pytest.

## Product context and non-negotiable boundary

RetObs is a flagship portfolio artifact for ML engineering, AI engineering, ML infrastructure, and FDE roles. The target user is an ML/AI platform engineer responsible for proving that a retrieval change is safe to promote across customer-facing RAG systems. The project should demonstrate reliable production judgment: explicit contracts, safe/reversible instrumentation, uncertainty-aware evaluation, local-first privacy, and refusal to claim more than captured evidence permits.

The product is not a generic RAG evaluator, answer evaluator, leaderboard, visual workflow builder, or broad observability replacement. Tools such as Langfuse, Phoenix, LangSmith, MLflow, Braintrust, Evidently, Ragas, and DeepEval already provide broad traces, datasets, evaluators, experiments, and CI features. Do not claim RetObs is the first or only tool to do any of those things. Its narrow contribution is the productized combination of:

1. evidence contracts and comparability checks before a release claim;
2. `BLOCK` for missing/invalid evidence and `HOLD` for valid but inconclusive evidence;
3. retrieval-specific candidate lineage across a runtime DAG, with explicit unknown and partial states;
4. a CI report that links a decision to the exact query, slice, stage, and candidate evidence requiring investigation.

The project must never imply external adoption, stars, downloads, production deployments, or general superiority. Public documentation must say that a `PASS` supports promotion **under the declared policy**, not that it proves universal safety or causal explanation.

## Global constraints

- Keep `retobs compare BASELINE CANDIDATE --policy PATH` as the only release-decision command. Do not add `retobs decide`.
- `PASS` means all policy-required promotion evidence is valid and every declared paired non-inferiority guard passes. Improvement is not required.
- `HOLD` means valid evidence is inconclusive; `BLOCK` means policy-required evidence is absent/invalid; `FAIL` means valid evidence proves an unacceptable regression.
- Return one `ReleaseDecision` plus claim-scoped readiness for `promotion`, `aggregate_or_slice_evaluation`, `lineage_diagnosis`, `lineage_diff`, and `production_trace`. Missing lineage must not block promotion unless the policy explicitly requires it.
- Policies accept exact canonical metric keys and exact top-level persisted metadata slice values only. Reject expressions, regexes, SQL, arbitrary Python, and post-hoc slice discovery.
- Use paired query bootstrap intervals for candidate-minus-baseline effects. Recompute `p50`/`p95`/`p99` under paired resampling; never render a mean delta as a percentile latency metric. Keep p-values/BH q-values diagnostic only.
- Preserve local-first behavior, loopback dashboard binding, reviewed `plan → apply → verify` integration, privacy/redaction controls, telemetry queue/overflow configuration, and no hosted account/deployment-management feature.
- Evolve existing components instead of duplicating them: `CandidateFlowWorkspace`, `DocumentPathSimulator`, `CandidateMissTable`, `candidate_history`, `candidate_journeys`, and candidate-flow API routes already exist.
- Replace TP/FP/FN/TN labels in the current candidate UI. “True negative” is not valid for the corpus-wide retrieval universe. Use operational outcome labels and mark relevance unknown when qrels/validated labels are unavailable.
- Treat legacy trace facts as `legacy_inferred`, `partial`, or `unavailable`; do not silently upgrade legacy inferred drop reasons into recorded evidence.
- Do not add a graph-visualization dependency. Use the existing SVG/layout utilities and React components for the V1 static DAG.
- Preserve unrelated worktree changes, including the existing `SECURITY.md` modification. Update `CHANGELOG.md` under `[Unreleased]` after every user-visible task.
- Run focused tests before each commit. No test or example may require network access, production traces, secrets, or raw user documents.

## Existing code to understand before Task 1

| File | Current responsibility | Planned evolution |
|---|---|---|
| `retrieval_observatory/tracing/model.py` | `Candidate`, `OperatorSpan`, `RetrievalTrace`, capture metadata | Add lineage-v2 identity, parentage, decision/evidence fields with legacy-compatible deserialization. |
| `retrieval_observatory/tracing/candidates.py` | Builds parent-grouped input/output transitions | Preserve exact candidate IDs and explicit parent relationships instead of matching only `doc_id`. |
| `retrieval_observatory/tracing/candidate_history.py` | Linear candidate event history | Build it from the new DAG read model and retain legacy inference labels. |
| `retrieval_observatory/tracing/candidate_journeys.py` | Query table for relevant/dropped candidates | Produce operational outcomes and evidence limits rather than TP/FP/FN/TN. |
| `retrieval_observatory/store/base.py`, `sqlite.py`, `postgres.py` | Trace contracts and trace storage | Add efficient query-scoped trace reads; lineage remains trace-derived for V1. |
| `retrieval_observatory/dashboard/api.py` | Run/query/candidate API | Add lineage graph, accounting, readiness, and comparison-diff endpoints while retaining existing candidate routes as aliases. |
| `retrieval_observatory/dashboard/ui/src/components/CandidateFlowWorkspace.tsx` | Existing candidate-flow workspace | Become the query-level Candidate Lineage Explorer entry point. |
| `retrieval_observatory/dashboard/ui/src/components/DocumentPathSimulator.tsx` | Animated linear path | Become optional replay; static candidate routes are the primary diagnostic surface. |
| `retrieval_observatory/sdk/report.py` | Markdown/HTML/JSON report model | Render decision, claim readiness, and safe deep-link identifiers. |

---

### Task 1: Add a bounded release-policy and claim-readiness contract

**Files:**
- Create: `retrieval_observatory/release/__init__.py`
- Create: `retrieval_observatory/release/policy.py`
- Create: `retrieval_observatory/release/readiness.py`
- Create: `tests/unit/test_release_policy.py`
- Create: `tests/fixtures/release_policy.yaml`
- Modify: `docs/EVIDENCE_AND_TRUST.md`
- Modify: `CHANGELOG.md`

**Consumes:** existing canonical metric-key parsing in `retrieval_observatory.metrics.comparison`.

**Produces:** `ReleasePolicy`, `EvidenceRequirements`, `LineageRequirements`, `StatisticsPolicy`, `MetricGuard`, `SliceGuard`, `ClaimReadiness`, and `load_release_policy(path)`.

- [ ] **Step 1: Write failing policy and readiness tests**

```python
def test_policy_separates_promotion_from_lineage_requirements(tmp_path):
    policy = load_release_policy(tmp_path / "policy.yaml")
    assert policy.evidence.promotion.min_label_coverage == 0.95
    assert policy.evidence.lineage_diagnosis.require_recorded_exit_reasons is True

def test_policy_rejects_dynamic_metric_and_nested_slice_selectors():
    with pytest.raises(ValidationError, match="exact canonical metric key"):
        ReleasePolicy.model_validate({"metrics": [{"metric": "ndcg.*", "direction": "higher_is_better"}]})
    with pytest.raises(ValidationError, match="top-level"):
        ReleasePolicy.model_validate({"slices": [{"id": "x", "field": "account.tier", "value": "pro"}]})
```

- [ ] **Step 2: Run the focused test**

Run: `pytest -q tests/unit/test_release_policy.py`

Expected: collection fails because `retrieval_observatory.release` does not exist.

- [ ] **Step 3: Implement strict Pydantic contracts**

```python
class EvidenceFinding(BaseModel):
    code: str
    scope: Literal["promotion", "aggregate_or_slice_evaluation", "lineage_diagnosis", "lineage_diff", "production_trace"]
    status: Literal["READY", "HOLD", "BLOCK"]
    observed: JsonValue | None = None
    required: JsonValue | None = None
    detail: str
    next_action: str

class PromotionEvidenceRequirements(BaseModel):
    required_manifest_fields: list[str] = Field(default_factory=list)
    min_label_coverage: float | None = Field(default=None, ge=0, le=1)
    max_sampled_out_rate: float | None = Field(default=None, ge=0, le=1)
    max_dropped_rate: float | None = Field(default=None, ge=0, le=1)

class LineageRequirements(BaseModel):
    require_stable_candidate_identity: bool = False
    min_input_output_coverage: float | None = Field(default=None, ge=0, le=1)
    require_recorded_exit_reasons: bool = False
    require_topology_alignment_for_diff: bool = True

class EvidenceRequirements(BaseModel):
    promotion: PromotionEvidenceRequirements = Field(default_factory=PromotionEvidenceRequirements)
    lineage_diagnosis: LineageRequirements = Field(default_factory=LineageRequirements)
    lineage_diff: LineageRequirements = Field(default_factory=LineageRequirements)

class ClaimReadiness(BaseModel):
    scope: Literal["promotion", "aggregate_or_slice_evaluation", "lineage_diagnosis", "lineage_diff", "production_trace"]
    status: Literal["READY", "HOLD", "BLOCK"]
    findings: list[EvidenceFinding]
```

Set `extra="forbid"` on all policy models. Validate canonical metric keys, nonnegative budgets, literal top-level slice fields, unique guard identities, and policy IDs. Define the exact `EvidenceFinding` model in this task so later tasks do not invent incompatible shapes.

- [ ] **Step 4: Add a privacy-safe complete fixture**

```yaml
id: support-search-v2
schema_version: 2
evidence:
  promotion:
    required_manifest_fields: [release_identity.index_build_id, release_identity.corpus_revision]
    min_label_coverage: 0.95
  lineage_diagnosis:
    require_stable_candidate_identity: true
    min_input_output_coverage: 0.99
    require_recorded_exit_reasons: true
statistics:
  confidence_level: 0.95
  familywise_alpha: 0.05
  resamples: 10000
  seed: 42
metrics:
  - metric: hybrid__rerank|stage1|ndcg@10
    direction: higher_is_better
    max_regression: 0.01
    min_paired_n: 100
```

- [ ] **Step 5: Verify, document, and commit**

Run: `pytest -q tests/unit/test_release_policy.py`

Expected: policy validation passes; malformed selectors and ambiguous evidence requirements fail deterministically.

Document that promotion readiness and lineage-diagnosis readiness are separate claims. Add a concise `[Unreleased]` entry and commit with: `feat: add scoped retrieval release policy`.

### Task 2: Upgrade the trace candidate model to the versioned lineage contract

**Files:**
- Modify: `retrieval_observatory/tracing/model.py`
- Modify: `retrieval_observatory/tracing/candidates.py`
- Modify: `retrieval_observatory/tracing/serialization.py`
- Create: `retrieval_observatory/tracing/lineage_contract.py`
- Modify: `tests/unit/test_parent_grouped_candidates.py`
- Modify: `tests/unit/test_trace_serialization.py`
- Create: `tests/unit/test_lineage_contract.py`
- Modify: `CHANGELOG.md`

**Consumes:** `ReleasePolicy` vocabulary only; no release-decision behavior yet.

**Produces:** a backward-compatible `Candidate`/`OperatorSpan` trace schema that can encode identity-preserving DAG lineage.

- [ ] **Step 1: Write failing contract tests for identity, derivation, and legacy traces**

```python
def test_fusion_output_retains_multiple_candidate_parents():
    fused = Candidate(candidate_id="fused:42", logical_chunk_id="chunk:42", parent_candidate_ids=("lex:42", "vec:42"), doc_id="chunk:42", score=.9, rank=1)
    assert fused.parent_candidate_ids == ("lex:42", "vec:42")

def test_legacy_doc_only_candidate_is_marked_legacy_inferred():
    candidate = Candidate.from_dict({"doc_id": "d1", "score": 1.0, "rank": 1})
    assert candidate.candidate_id == "d1"
    assert candidate.identity_evidence == "legacy_inferred"
```

- [ ] **Step 2: Run the focused test**

Run: `pytest -q tests/unit/test_lineage_contract.py tests/unit/test_trace_serialization.py`

Expected: tests fail because lineage-v2 fields and validation do not exist.

- [ ] **Step 3: Implement the smallest compatible model extension**

```python
LineageEvidence = Literal["recorded", "legacy_inferred", "partial", "unavailable"]

@dataclass
class Candidate:
    doc_id: str
    score: float
    rank: int
    candidate_id: str | None = None
    logical_chunk_id: str | None = None
    document_id: str | None = None
    document_revision: str | None = None
    content_hash: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    parent_candidate_ids: tuple[str, ...] = ()
    identity_evidence: LineageEvidence = "recorded"
    decision_reason: str | None = None
    decision_evidence: LineageEvidence = "unavailable"
```

Normalize missing legacy `candidate_id` and `logical_chunk_id` to `doc_id`, set `identity_evidence="legacy_inferred"`, and preserve existing `add_reason`/`drop_reason` for compatibility. Validate that a recorded derived candidate has at least one declared parent and that a candidate ID is unique within each input/output set. Do not reject old traces merely because they lack v2 fields.

- [ ] **Step 4: Change transition construction to match candidate IDs before document IDs**

Update `build_candidate_transition` to retain each source candidate's ID, propagate parent candidate IDs into pass-through outputs, and record a structured `decision_reason` only when supplied by instrumentation. Existing operator-type guesses remain available only as `decision_evidence="legacy_inferred"`; they cannot satisfy a policy requiring recorded exits.

- [ ] **Step 5: Verify compatibility and commit**

Run: `pytest -q tests/unit/test_lineage_contract.py tests/unit/test_parent_grouped_candidates.py tests/unit/test_trace_serialization.py tests/unit/test_trace_identity_contract.py`

Expected: v2 traces preserve branch/fusion parentage; current trace fixtures still deserialize; inferred facts remain visibly inferred.

Add an `[Unreleased]` entry and commit with: `feat: add versioned retrieval candidate lineage contract`.

### Task 3: Make query-scoped lineage reads efficient in both stores

**Files:**
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/store/migrate.py`
- Modify: `tests/unit/test_store_unified_sqlite.py`
- Modify: `tests/unit/test_store_postgres.py`
- Create: `tests/unit/test_trace_query_scope.py`
- Modify: `CHANGELOG.md`

**Consumes:** the v2 trace schema from Task 2.

**Produces:** `TraceQuery(run_id=..., query_id=...)` and an indexed query-scoped trace read. V1 lineage is derived from trace records; do not introduce a redundant candidate-lineage table.

- [ ] **Step 1: Write a store-contract test**

```python
@pytest.mark.asyncio
async def test_list_traces_filters_run_and_query_id(store):
    await store.save_traces([_trace("run-a", "q-1"), _trace("run-a", "q-2"), _trace("run-b", "q-1")])
    rows = await store.list_traces(TraceQuery(run_id="run-a", query_id="q-1"))
    assert [(row.run_id, row.query_id) for row in rows] == [("run-a", "q-1")]
```

- [ ] **Step 2: Run the focused tests**

Run: `pytest -q tests/unit/test_trace_query_scope.py tests/unit/test_store_unified_sqlite.py`

Expected: construction fails because `TraceQuery` lacks `query_id`.

- [ ] **Step 3: Add the contract and both backend implementations**

```python
@dataclass(frozen=True)
class TraceQuery:
    run_id: str | None = None
    query_id: str | None = None
    service_id: str | None = None
    pipeline_id: str | None = None
    topology_hash: str | None = None
```

Add `query_id` filtering to SQLite and PostgreSQL query construction. Add `idx_traces_run_query` on `(run_id, query_id)` through existing migration-safe table/index setup. Keep current methods and positional behavior compatible. Use the query filter in every new lineage endpoint rather than loading all traces for a run.

- [ ] **Step 4: Add cross-backend migration tests**

Assert an upgraded SQLite database gets the index safely, the PostgreSQL query includes `query_id`, and a no-query filter returns existing behavior. Do not persist content previews or candidate data outside existing redacted trace JSON.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_trace_query_scope.py tests/unit/test_store_unified_sqlite.py tests/unit/test_store_postgres.py tests/unit/test_store_contract.py`

Expected: only the selected query's traces are loaded and legacy storage remains readable.

Add an `[Unreleased]` entry and commit with: `feat: add query-scoped trace retrieval`.

### Task 4: Capture release identity and evidence profiles with lineage completeness

**Files:**
- Create: `retrieval_observatory/release/evidence.py`
- Modify: `retrieval_observatory/runner/execute.py`
- Modify: `retrieval_observatory/runner/manifest.py`
- Modify: `retrieval_observatory/config/schema.py`
- Create: `tests/unit/test_release_evidence.py`
- Modify: `tests/integration/test_api_run_roundtrip.py`
- Modify: `CHANGELOG.md`

**Consumes:** policy types, v2 traces, query-scoped stores.

**Produces:** `ReleaseIdentity`, `LineageCoverage`, `EvidenceProfile.from_run(...)`, and run-window-bound telemetry evidence.

- [ ] **Step 1: Write tests that distinguish absent, partial, and complete lineage**

```python
def test_profile_counts_recorded_exit_coverage_not_inferred_exits():
    profile = EvidenceProfile.from_run(_manifest(), [_trace(recorded_exit=True), _trace(recorded_exit=False)], _health_window())
    assert profile.lineage.recorded_exit_reason_coverage == 0.5
    assert profile.lineage.identity_continuity_coverage == 1.0

def test_profile_keeps_health_outside_run_window_unknown():
    assert EvidenceProfile.from_run(_manifest(), [_trace()], _health_window(outside=True)).telemetry is None
```

- [ ] **Step 2: Run the focused test**

Run: `pytest -q tests/unit/test_release_evidence.py`

Expected: collection fails because `EvidenceProfile` is absent.

- [ ] **Step 3: Implement explicit identity and coverage models**

```python
class ReleaseIdentityConfig(BaseModel):
    service_id: str | None = None
    deployment_revision: str | None = None
    corpus_revision: str | None = None
    index_build_id: str | None = None
    chunking_revision: str | None = None
    embedding_model_revision: str | None = None
    reranker_model_revision: str | None = None

class LineageCoverage(BaseModel):
    trace_coverage: float | None
    identity_continuity_coverage: float | None
    input_output_coverage: float | None
    recorded_exit_reason_coverage: float | None
    topology_edge_coverage: float | None
    qrel_to_chunk_mapping_coverage: float | None
    legacy_inferred_count: int
    partial_trace_count: int
```

Derive coverage only from observed traces in the run window. Keep unknown values `None`, never `0.0`. Preserve sorted topology signatures and add a canonical topology descriptor containing operator IDs/types/parents and lineage schema versions.

- [ ] **Step 4: Persist profile and time window during evaluation completion**

Persist the evidence profile with the final manifest after metrics and traces exist. Request health only for `[run.started_at, run.finished_at]`, or leave telemetry unknown when no window-compatible measurement exists. Do not use a latest service health value for an earlier run.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_release_evidence.py tests/integration/test_api_run_roundtrip.py tests/unit/test_trace_run_scoping.py`

Expected: manifests contain reproducible identity and lineage coverage; unknown health remains unknown.

Add an `[Unreleased]` entry and commit with: `feat: persist scoped retrieval evidence profiles`.

### Task 5: Assess promotion and diagnostic evidence independently

**Files:**
- Create: `retrieval_observatory/release/assessment.py`
- Modify: `retrieval_observatory/metrics/comparison.py`
- Create: `tests/unit/test_release_assessment.py`
- Modify: `tests/unit/test_comparison_contract.py`
- Modify: `CHANGELOG.md`

**Consumes:** `ReleasePolicy`, `EvidenceProfile`, existing `comparison_validity`.

**Produces:** `EvidenceAssessment` with a `ClaimReadiness` item for every scope and stable `EvidenceFinding` codes.

- [ ] **Step 1: Write scoped-assessment tests**

```python
def test_complete_final_metrics_can_pass_promotion_while_lineage_blocks():
    assessment = assess_evidence(_policy(requires_lineage_for_promotion=False), _complete_manifest(lineage_exit_coverage=.5), _complete_manifest(lineage_exit_coverage=.5))
    assert assessment.readiness["promotion"].status == "READY"
    assert assessment.readiness["lineage_diagnosis"].status == "BLOCK"

def test_required_corpus_revision_blocks_promotion():
    assessment = assess_evidence(_policy(), _manifest(corpus_revision=None), _manifest(corpus_revision="v2"))
    assert assessment.readiness["promotion"].status == "BLOCK"
```

- [ ] **Step 2: Run the focused tests**

Run: `pytest -q tests/unit/test_release_assessment.py tests/unit/test_comparison_contract.py`

Expected: collection fails because `assess_evidence` is absent.

- [ ] **Step 3: Implement exact readiness rules**

Promotion requires equality of query/corpus/qrel hashes where existing comparability requires it, presence of each policy-required identity field, and policy-required coverage/telemetry limits. Lineage diagnosis checks v2 identity continuity, input/output coverage, recorded exit reason coverage, truncation, and partial-capture flags. Lineage diff additionally checks stable logical chunk/document revision identity and topology semantics. A topology change may remain valid for end-to-end promotion but blocks stage-aligned diff unless the policy explicitly maps equivalent stages.

- [ ] **Step 4: Define stable findings and next-action metadata**

Use exact codes such as `required_manifest_field_missing`, `comparison_identity_mismatch`, `telemetry_window_unavailable`, `lineage_identity_partial`, `lineage_exit_reason_unrecorded`, `lineage_topology_unaligned`, and `qrel_chunk_mapping_incomplete`. Every finding includes `scope`, `status`, `observed`, `required`, and a concrete next action.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_release_assessment.py tests/unit/test_comparison_contract.py tests/unit/test_comparability.py`

Expected: no absent evidence becomes a passing claim; diagnosis can be blocked independently of promotion.

Add an `[Unreleased]` entry and commit with: `feat: assess retrieval evidence by claim scope`.

### Task 6: Add paired effect intervals, declared slices, and the decision state machine

**Files:**
- Create: `retrieval_observatory/release/statistics.py`
- Create: `retrieval_observatory/release/slices.py`
- Create: `retrieval_observatory/release/decision.py`
- Modify: `retrieval_observatory/metrics/significance.py`
- Modify: `retrieval_observatory/metrics/comparison.py`
- Create: `tests/unit/test_release_statistics.py`
- Create: `tests/unit/test_release_slices.py`
- Create: `tests/unit/test_release_decision.py`
- Modify: `CHANGELOG.md`

**Consumes:** policy, scoped evidence assessment, persisted metric rows.

**Produces:** reproducible paired interval guard results, declared slice results, and `ReleaseDecision`.

- [ ] **Step 1: Write deterministic interval, slice, and precedence tests**

```python
def test_p95_resampling_recomputes_quantile_not_mean():
    low, high = paired_bootstrap_effect_ci([1.0] * 95 + [100.0] * 5, [1.0] * 95 + [200.0] * 5, estimator="p95", n_resamples=500, confidence_level=.95, seed=7)
    assert high > 50.0

def test_absent_required_slice_blocks_and_crossing_interval_holds():
    assert evaluate_declared_slices(_policy(required_slice="enterprise"), _rows("support"), _rows("support"))[0].status == "BLOCK"
    assert decide_release(_policy(), _ready_assessment(), [_crossing_guard()], []).status == "HOLD"
```

- [ ] **Step 2: Run the focused tests**

Run: `pytest -q tests/unit/test_release_statistics.py tests/unit/test_release_slices.py tests/unit/test_release_decision.py`

Expected: imports fail because the release statistics, slice, and decision modules are absent.

- [ ] **Step 3: Implement paired-index bootstrap and exact guard semantics**

```python
def paired_bootstrap_effect_ci(baseline: Sequence[float], candidate: Sequence[float], *, estimator: Literal["mean", "p50", "p95", "p99"], n_resamples: int, confidence_level: float, seed: int) -> tuple[float | None, float | None]: ...

class ReleaseDecision(BaseModel):
    status: Literal["PASS", "HOLD", "BLOCK", "FAIL"]
    reasons: list[str]
    readiness: dict[str, ClaimReadiness]
    aggregate_guards: list[GuardResult]
    slices: list[SliceResult]
    next_action: str
    policy: PolicyReference
```

Use the same sampled index vector for baseline and candidate. For a percentile estimator, recompute `numpy.quantile` on each paired resample. Count all declared aggregate and slice guards before applying family-wise adjustment. Status precedence is `BLOCK`, then `FAIL`, then `HOLD`, then `PASS` for promotion evidence only.

- [ ] **Step 4: Implement declared-slice pairing without post-hoc discovery**

Filter persisted `query_metadata[field]` by exact literal, then join baseline/candidate rows by query ID before every interval. Expose paired count, label coverage, adjusted confidence, and sample limitation. Do not infer a lineage causal slice conclusion from metric results; lineage accounting is a later diagnostic read model.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_release_statistics.py tests/unit/test_release_slices.py tests/unit/test_release_decision.py tests/unit/test_comparison_contract.py`

Expected: deterministic intervals, correct percentile semantics, stable decision precedence, and no policy-less `PASS`.

Add an `[Unreleased]` entry and commit with: `feat: add uncertainty-aware retrieval release decisions`.

### Task 7: Render and expose one canonical release artifact

**Files:**
- Modify: `retrieval_observatory/sdk/report.py`
- Modify: `retrieval_observatory/sdk/api.py`
- Modify: `retrieval_observatory/cli.py`
- Modify: `retrieval_observatory/mcp/server.py`
- Modify: `contracts/public_surface.json`
- Create: `tests/unit/test_release_report.py`
- Create: `tests/unit/test_release_cli.py`
- Create: `tests/unit/test_release_sdk_mcp.py`
- Modify: `tests/contracts/test_public_surface.py`
- Modify: `CHANGELOG.md`

**Consumes:** decision/state models from Tasks 1–6.

**Produces:** schema-versioned report JSON/Markdown/HTML, CLI/SDK/MCP access, and CI exit behavior.

- [ ] **Step 1: Write report and boundary tests**

```python
def test_report_contains_overall_decision_and_lineage_readiness():
    payload = _comparison_report(status="FAIL", lineage_status="BLOCK").to_dict()["comparison"]["release_decision"]
    assert payload["status"] == "FAIL"
    assert payload["readiness"]["lineage_diagnosis"]["status"] == "BLOCK"

def test_strict_compare_exits_nonzero_for_hold(cli_runner, prepared_db, policy_path):
    result = cli_runner.invoke(app, ["compare", "base", "candidate", "--db", prepared_db, "--policy", policy_path, "--fail-on", "hold-or-block-or-fail"])
    assert result.exit_code == 1
    assert "Verdict: HOLD" in result.stdout
```

- [ ] **Step 2: Run focused tests**

Run: `pytest -q tests/unit/test_release_report.py tests/unit/test_release_cli.py tests/unit/test_release_sdk_mcp.py`

Expected: tests fail because the report has no release decision and compare accepts no policy.

- [ ] **Step 3: Build one report payload and render safe investigation references**

`load_comparison_report(...)` loads manifests, query-scoped metrics/traces, evidence profiles, assessment, guards, slices, and one decision. Render status; policy ID/schema/digest; provenance; claim-readiness matrix; evidence findings; intervals; slices; affected query IDs; next action; and reproduce command before raw metric tables. Include route templates/IDs, not raw query text or chunk content, in report summaries.

- [ ] **Step 4: Add boundaries without adding a decision command**

Add `--policy PATH` to `retobs compare`; accept `policy: str | Path | ReleasePolicy | None` in SDK compare; accept only explicit local `policy_path` in MCP. Canonical `--fail-on` values are `never`, `fail`, and `hold-or-block-or-fail`; map old values for one release cycle with a deprecation warning. A no-policy compare returns `HOLD` in the artifact but exits zero by default.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_release_report.py tests/unit/test_release_cli.py tests/unit/test_release_sdk_mcp.py tests/contracts/test_public_surface.py`

Expected: every interface serializes the same decision and the browser never has to calculate release status itself.

Add an `[Unreleased]` entry and commit with: `feat: expose retrieval release evidence artifacts`.

### Task 8: Preflight lineage capture and add a standards-oriented adapter boundary

**Files:**
- Modify: `retrieval_observatory/integrations/verify.py`
- Modify: `retrieval_observatory/cli.py`
- Create: `retrieval_observatory/tracing/adapters/__init__.py`
- Create: `retrieval_observatory/tracing/adapters/otel.py`
- Create: `tests/unit/test_release_integration_verify.py`
- Create: `tests/unit/test_otel_lineage_adapter.py`
- Modify: `docs/INTEGRATIONS.md`
- Modify: `CHANGELOG.md`

**Consumes:** lineage contract and scoped evidence requirements.

**Produces:** policy preflight and an optional attribute-mapping boundary for OpenTelemetry-style retrieval data; source patching remains optional.

- [ ] **Step 1: Write preflight and adapter tests**

```python
async def test_verify_blocks_only_lineage_diagnosis_when_exits_are_missing(tmp_path, store):
    result = await verify_project(tmp_path, store, policy=_policy(require_recorded_exits=True))
    assert result.release_readiness["lineage_diagnosis"]["status"] == "BLOCK"

def test_otel_adapter_marks_missing_parentage_partial():
    trace = normalize_otel_retrieval_trace(_otel_span_without_candidate_parents())
    assert trace.capture.lineage_evidence == "partial"
```

- [ ] **Step 2: Run focused tests**

Run: `pytest -q tests/unit/test_release_integration_verify.py tests/unit/test_otel_lineage_adapter.py`

Expected: `verify_project` rejects policy and the adapter module is missing.

- [ ] **Step 3: Reuse assessment in integration verification**

`retobs integrate ROOT --phase verify --policy PATH` builds a partial `EvidenceProfile` and evaluates only verifiable capture requirements: stable identity, stage input/output groups, recorded exits, topology edges, and telemetry health. It must mark labels and paired metrics unavailable rather than passing them. It prints promotion and lineage readiness separately.

- [ ] **Step 4: Implement a dependency-light OTel attribute mapper**

```python
def normalize_otel_retrieval_trace(span: Mapping[str, Any]) -> RetrievalTrace:
    """Map already-exported OTel/OpenInference-like retrieval attributes into RetObs traces.

    Unknown candidate identity, parentage, or exits become partial/unavailable capture;
    this function never fabricates transition edges.
    """
```

Do not add an OTel SDK dependency. Map only fields actually present; document RetObs lineage extension keys in `docs/INTEGRATIONS.md`. Existing reviewed plan/apply/verify wiring remains available when standards telemetry is insufficient.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_release_integration_verify.py tests/unit/test_otel_lineage_adapter.py tests/unit/test_integration_cli.py tests/unit/test_instrumentation_health_api.py`

Expected: integration tells an engineer what evidence is missing before evaluation and adapter gaps remain explicit.

Add an `[Unreleased]` entry and commit with: `feat: preflight retrieval lineage evidence`.

### Task 9: Build the trace-derived candidate-lineage read model and outcome accounting

**Files:**
- Create: `retrieval_observatory/tracing/lineage.py`
- Create: `retrieval_observatory/tracing/lineage_accounting.py`
- Modify: `retrieval_observatory/tracing/candidate_history.py`
- Modify: `retrieval_observatory/tracing/candidate_journeys.py`
- Modify: `retrieval_observatory/tracing/replay.py`
- Create: `tests/unit/test_candidate_lineage.py`
- Create: `tests/unit/test_lineage_accounting.py`
- Modify: `tests/unit/test_parent_grouped_candidates.py`
- Modify: `CHANGELOG.md`

**Consumes:** v2 trace data and qrels.

**Produces:** `CandidateLineageGraph`, `CandidateRoute`, `CandidatePassport`, `StageLossAccounting`, and operational outcome classification.

- [ ] **Step 1: Write graph, unknown-relevance, and partial-capture tests**

```python
def test_graph_preserves_two_routes_into_a_fused_candidate():
    graph = build_candidate_lineage(_fusion_trace(), qrels={"q1": {"chunk:42": 1}})
    assert set(graph.candidates["fused:42"].parent_candidate_ids) == {"lex:42", "vec:42"}
    assert len(graph.candidates["fused:42"].routes) == 2

def test_unlabeled_production_candidate_is_unknown_not_false_positive():
    outcome = classify_candidate_outcome(_passport_without_qrels())
    assert outcome.kind == "unknown_relevance"

def test_missing_operator_output_marks_lineage_incomplete_not_dropped():
    assert build_candidate_lineage(_partial_trace()).candidates["c1"].lineage_evidence == "partial"
```

- [ ] **Step 2: Run focused tests**

Run: `pytest -q tests/unit/test_candidate_lineage.py tests/unit/test_lineage_accounting.py`

Expected: imports fail because the lineage modules are absent.

- [ ] **Step 3: Implement immutable graph/read-model types**

```python
@dataclass(frozen=True)
class CandidatePassport:
    candidate_id: str
    logical_chunk_id: str | None
    source: CandidateSource
    parent_candidate_ids: tuple[str, ...]
    routes: tuple[CandidateRoute, ...]
    relevance: RelevanceEvidence
    outcome: CandidateOutcome
    lineage_evidence: LineageEvidence

def build_candidate_lineage(trace: RetrievalTrace, *, qrels_for_query: Mapping[str, int], qrel_chunk_mapping_complete: bool) -> CandidateLineageGraph: ...
```

Build edges exclusively from recorded input/output candidate IDs and explicit parent relationships. For old traces, preserve candidate-history inference as a labeled compatibility projection. A candidate absent from a partial output is `lineage_incomplete`, not `relevant_dropped_at_stage`.

- [ ] **Step 4: Implement correct operational outcomes and stage accounting**

`classify_candidate_outcome` emits only the seven terms in the design. `relevant_lost_upstream` requires both validated relevance and complete retrieval-entry observation; otherwise emit `lineage_incomplete`. `StageLossAccounting` groups each outcome by operator, branch, and evidence class and includes `unknown_relevance_count` and `incomplete_lineage_count`. Update candidate journeys to return `outcome` and `outcome_evidence` instead of `relevant`-derived TP/FP/FN/TN labels.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_candidate_lineage.py tests/unit/test_lineage_accounting.py tests/unit/test_parent_grouped_candidates.py tests/unit/test_trace_identity_contract.py`

Expected: fusion/branch paths survive, legacy drops remain inferred, and unlabeled traces never receive a relevance verdict.

Add an `[Unreleased]` entry and commit with: `feat: derive evidence-aware retrieval candidate lineage`.

### Task 10: Add lineage, accounting, and candidate-passport APIs

**Files:**
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/analysis_api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Create: `tests/unit/test_dashboard_lineage_api.py`
- Modify: `tests/unit/test_dashboard_multi_db_api.py`
- Modify: `CHANGELOG.md`

**Consumes:** query-scoped traces, evidence profile, lineage graph/read model.

**Produces:** stable local API payloads that retain current candidate routes as compatibility aliases.

- [ ] **Step 1: Write API contract tests**

```python
def test_query_lineage_api_returns_graph_accounting_and_readiness(client, seeded_db):
    payload = client.get("/api/db/default/runs/run-a/queries/q-1/candidate-lineage").json()
    assert payload["readiness"]["scope"] == "lineage_diagnosis"
    assert payload["accounting"]["relevant_dropped_at_stage"] == 1
    assert payload["graph"]["edges"]

def test_passport_api_does_not_return_raw_preview_when_redacted(client, redacted_db):
    payload = client.get("/api/db/default/runs/run-a/queries/q-1/candidates/c-1").json()
    assert payload["source"]["preview"] is None
```

- [ ] **Step 2: Run focused tests**

Run: `pytest -q tests/unit/test_dashboard_lineage_api.py`

Expected: the new lineage endpoint and readiness payload do not exist.

- [ ] **Step 3: Implement query-scoped endpoints**

Implement:

```text
GET /runs/{run_id}/queries/{query_id}/candidate-lineage
GET /runs/{run_id}/queries/{query_id}/candidates/{candidate_id}
GET /runs/{run_id}/queries/{query_id}/lineage-accounting
```

Load traces using `TraceQuery(run_id=..., query_id=...)`. Return graph nodes/edges, outcome counts, candidate IDs, readiness, and evidence warnings. Retain existing `/candidate-journeys` and `/candidates/{doc_id}` routes as adapters to the new read model for one release cycle.

- [ ] **Step 4: Enforce content and evidence boundaries**

Use existing redaction metadata to omit preview/text when redacted or omitted. Return `unknown_relevance` rather than `False` when no qrels exist. Return HTTP 404 only when no query traces exist; return HTTP 200 with `lineage_diagnosis: BLOCK` when traces exist but lineage is incomplete.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_dashboard_lineage_api.py tests/unit/test_dashboard_multi_db_api.py tests/unit/test_trace_redaction.py`

Expected: API payloads are query-scoped, privacy-safe, and distinguish no trace from incomplete lineage.

Add an `[Unreleased]` entry and commit with: `feat: expose retrieval candidate lineage APIs`.

### Task 11: Make Compare decision-first and evolve the existing candidate UI into a static Explorer

**Files:**
- Modify: `retrieval_observatory/dashboard/ui/src/components/ComparePanel.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/ReleaseDecisionCard.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/ReleaseEvidenceMatrix.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/ReleaseSliceTable.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/CandidateFlowWorkspace.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/CandidateMissTable.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/DocumentPathSimulator.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/CandidateLineageGraph.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/CandidatePassport.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/StageLossAccounting.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/ReleaseDecisionCard.test.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/CandidateLineageGraph.test.tsx`
- Create: `retrieval_observatory/dashboard/ui/src/components/CandidateOutcomeTable.test.tsx`
- Modify: `tests/browser/test_dashboard_workflow.py`
- Modify: `CHANGELOG.md`

**Consumes:** canonical report/API shape and lineage API payloads.

**Produces:** release decision → slice → affected query → static DAG → passport interaction, with optional recorded replay.

- [ ] **Step 1: Write component tests for correct evidence language**

```tsx
it('shows a blocked lineage claim without changing a passing promotion decision', () => {
  render(<ReleaseDecisionCard decision={passWithBlockedLineage} onQueryMetricSelect={vi.fn()} />)
  expect(screen.getByText('PASS')).toBeVisible()
  expect(screen.getByText(/lineage diagnosis.*BLOCK/i)).toBeVisible()
})

it('never renders TN for an observed irrelevant removed candidate', () => {
  render(<CandidateOutcomeTable rows={[irrelevantRemovedRow]} onSelect={vi.fn()} />)
  expect(screen.getByText('Irrelevant removed')).toBeVisible()
  expect(screen.queryByText('TN')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run focused UI tests**

Run: `cd retrieval_observatory/dashboard/ui && npm test -- ReleaseDecisionCard.test.tsx CandidateLineageGraph.test.tsx CandidateOutcomeTable.test.tsx --run`

Expected: modules and outcome language are absent.

- [ ] **Step 3: Add the decision-first comparison surface**

Render overall decision, policy digest, claim-readiness matrix, evidence findings, paired intervals, and declared slice table before raw metrics. Selecting a failed/held guard navigates to an affected query. No TypeScript component calculates `PASS`/`HOLD`/`BLOCK`/`FAIL` from p-values or directional values.

- [ ] **Step 4: Replace the current linear/animation-first candidate flow**

`CandidateFlowWorkspace` loads `/candidate-lineage`, renders `CandidateLineageGraph` first, then `StageLossAccounting`, outcome table, and `CandidatePassport`. The graph is SVG-based, supports branch/reconvergence, has textual alternatives and keyboard selection, and uses shapes/text in addition to color. `DocumentPathSimulator` moves beneath a collapsible "Replay recorded transitions" section; it must say it replays captured events and does not re-execute the pipeline.

- [ ] **Step 5: Verify browser behavior and commit**

Run: `cd retrieval_observatory/dashboard/ui && npm test -- --run`

Run: `pytest -q tests/browser/test_dashboard_workflow.py`

Expected: users reach an affected query from a decision, inspect static branch-aware paths, select a candidate, and see explicit unknown/partial evidence states.

Add an `[Unreleased]` entry and commit with: `feat: add candidate lineage investigation explorer`.

### Task 12: Add valid baseline/candidate candidate-lineage diffs

**Files:**
- Create: `retrieval_observatory/tracing/lineage_diff.py`
- Modify: `retrieval_observatory/dashboard/api.py`
- Modify: `retrieval_observatory/dashboard/ui/src/api.ts`
- Create: `retrieval_observatory/dashboard/ui/src/components/CandidateLineageDiff.tsx`
- Modify: `retrieval_observatory/dashboard/ui/src/components/QueryDiffPage.tsx`
- Create: `tests/unit/test_lineage_diff.py`
- Create: `retrieval_observatory/dashboard/ui/src/components/CandidateLineageDiff.test.tsx`
- Modify: `CHANGELOG.md`

**Consumes:** lineage graphs and `lineage_diff` readiness.

**Produces:** an evidence-qualified comparison of candidate paths for a paired query.

- [ ] **Step 1: Write valid and invalid alignment tests**

```python
def test_diff_highlights_rank_and_exit_change_for_aligned_chunk():
    result = diff_candidate_lineage(_baseline_graph(), _candidate_graph(), readiness=_ready())
    assert result.changed[0].kind == "exit_changed"

def test_unaligned_document_revisions_block_stage_diff_but_keep_sides():
    result = diff_candidate_lineage(_graph(doc_revision="a"), _graph(doc_revision="b"), readiness=_blocked())
    assert result.status == "BLOCK"
    assert result.baseline is not None and result.candidate is not None
```

- [ ] **Step 2: Run focused tests**

Run: `pytest -q tests/unit/test_lineage_diff.py`

Expected: import fails because `lineage_diff` is absent.

- [ ] **Step 3: Implement identity-first diff semantics**

Match by `logical_chunk_id`, document revision/content hash, and query ID. Report `newly_surfaced`, `newly_dropped`, `newly_retained`, `rank_shifted`, `branch_changed`, and `exit_changed`. A changed topology without declared stage equivalence returns `BLOCK` readiness for stage alignment and displays side-by-side graphs only. Do not call a changed path a cause.

- [ ] **Step 4: Expose and render the diff**

Add a two-run query lineage endpoint that consumes already selected baseline/candidate IDs. `CandidateLineageDiff` shows status/reason first, then aligned changes or side-by-side graphs. Link it only from comparison affected queries, not arbitrary unpaired runs.

- [ ] **Step 5: Verify and commit**

Run: `pytest -q tests/unit/test_lineage_diff.py`

Run: `cd retrieval_observatory/dashboard/ui && npm test -- CandidateLineageDiff.test.tsx --run`

Expected: valid diffs expose observed path changes; invalid alignments refuse causal-looking comparison.

Add an `[Unreleased]` entry and commit with: `feat: compare retrieval candidate lineage safely`.

### Task 13: Publish the local/CI workflow and prove the complete system

**Files:**
- Create: `docs/guides/retrieval-release-decisions.md`
- Create: `docs/guides/candidate-lineage-explorer.md`
- Create: `examples/ci/release-policy.yaml`
- Modify: `examples/ci/retrieval-ci.yml`
- Modify: `README.md`
- Modify: `docs/WORKFLOW.md`
- Modify: `docs/PR_WORKFLOW.md`
- Modify: `docs/REFERENCE.md`
- Create: `tests/contracts/test_release_policy_example.py`
- Create: `tests/integration/test_release_decision_workflow.py`
- Create: `tests/integration/test_candidate_lineage_workflow.py`
- Modify: `scripts/generate_release_evidence.py`
- Modify: `tests/contracts/test_release_evidence.py`
- Modify: `CHANGELOG.md`

**Consumes:** every previous task.

**Produces:** reproducible no-secret documentation, example policy/CI, and deterministic proof fixtures for decision and lineage behavior.

- [ ] **Step 1: Write end-to-end fixtures for the decision/lineage boundary**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize((fixture_name, expected), [
    ("pass_with_lineage_blocked", "PASS"),
    ("held_underpowered_slice", "HOLD"),
    ("blocked_corpus_identity", "BLOCK"),
    ("failed_temporal_filter_slice", "FAIL"),
])
async def test_release_workflow_emits_expected_status(tmp_path, fixture_name, expected):
    report = await _run_fixture_and_compare(tmp_path, fixture_name)
    assert report.comparison["release_decision"]["status"] == expected
```

- [ ] **Step 2: Run focused integration tests**

Run: `pytest -q tests/integration/test_release_decision_workflow.py tests/integration/test_candidate_lineage_workflow.py`

Expected: files are absent before implementation is complete.

- [ ] **Step 3: Build fixed local fixtures and evidence assertions**

Create deterministic SQLite traces for a linear pipeline, routed two-branch fusion, relevant candidate dropped by a temporal filter, missing output capture, document-revision mismatch, and redacted preview. Assert: no-policy cannot pass; promotion can pass while lineage diagnosis blocks; unlabeled production candidates are unknown; an incomplete path is not reported as a drop; HTML/JSON contain no external dependencies or raw redacted text.

- [ ] **Step 4: Document the precise product position and workflow**

Document commands:

```bash
retobs integrate . --phase verify --policy retobs/release-policy.yaml
retobs compare BASELINE CANDIDATE --policy retobs/release-policy.yaml --format html --output artifacts/retobs-release.html --fail-on hold-or-block-or-fail
retobs serve --db .retobs/results.db
```

Explain `PASS`/`HOLD`/`BLOCK`/`FAIL`, claim-scoped readiness, identity requirements, qrel-to-chunk limits, operational candidate outcomes, static graph versus recorded replay, privacy posture, and how RetObs complements existing observability/evaluation platforms. Do not make adoption, superiority, or causal claims.

- [ ] **Step 5: Run the complete validation set and commit**

Run: `pytest -q tests/unit/test_release_policy.py tests/unit/test_lineage_contract.py tests/unit/test_trace_query_scope.py tests/unit/test_release_evidence.py tests/unit/test_release_assessment.py tests/unit/test_release_statistics.py tests/unit/test_release_slices.py tests/unit/test_release_decision.py tests/unit/test_release_report.py tests/unit/test_release_cli.py tests/unit/test_release_sdk_mcp.py tests/unit/test_release_integration_verify.py tests/unit/test_otel_lineage_adapter.py tests/unit/test_candidate_lineage.py tests/unit/test_lineage_accounting.py tests/unit/test_dashboard_lineage_api.py tests/unit/test_lineage_diff.py tests/integration/test_release_decision_workflow.py tests/integration/test_candidate_lineage_workflow.py tests/contracts/test_release_policy_example.py tests/contracts/test_release_evidence.py tests/contracts/test_public_surface.py`

Run: `ruff check retrieval_observatory tests`

Run: `cd retrieval_observatory/dashboard/ui && npm test -- --run`

Run: `python scripts/check_markdown_links.py`

Expected: all tests pass locally without network access; reports are deterministic under policy seeds; docs contain only supportable claims.

Add final `[Unreleased]` entries and commit with: `docs: add retrieval release evidence and candidate lineage workflow`.

## Plan self-review

- **Release foundation:** Tasks 1, 4, 5, 6, and 7 implement bounded policy, run identity, evidence assessment, statistical decisions, canonical reports, CI, CLI, SDK, and MCP.
- **Candidate lineage:** Tasks 2, 3, 8, 9, and 10 make stable candidate identity, DAG transitions, safe integration verification, query-scoped reads, outcome accounting, APIs, and static exploration real.
- **Decision-to-diagnosis connection:** Tasks 7, 11, and 12 link failed/held guards to affected queries and valid baseline/candidate path differences without claiming causality from mere correlation.
- **Reliability/privacy:** Tasks 2–4, 8–10, and 13 preserve explicit partial/unknown evidence, bind telemetry to decision windows, use local redaction, and cover failure fixtures.
- **Scope discipline:** The plan intentionally excludes answer-quality evaluation, hosted collaboration, a generic trace product, arbitrary policy code, a graph library, automatic tuning, and animation as the primary user experience.
- **Compatibility:** Existing `compare` fields, legacy fail-on aliases, candidate routes, and legacy traces remain available for one release cycle. New data surfaces distinguish recorded lineage from legacy inference.
