# Diagnostic and Evidence Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace snapshot-order and pipeline-name heuristics with trace-native, candidate-transition diagnostics whose prerequisites, evidence strength, supporting facts, limitations, and unavailable states are explicit and testable.

**Architecture:** Introduce a typed diagnostic model and independent rules evaluated over a `DiagnosticContext` built from the sole trace contract. Persist versioned findings once, then make query evidence, recommendations, APIs, and UI consume the same representation without reinterpreting labels.

**Tech Stack:** Python 3.10+, dataclasses/Pydantic conventions already used by retobs, pytest, SQLite/PostgreSQL store contracts, unified traces and parent-grouped candidates from Workstreams 2 and 4.

## Global Constraints

- Candidate transitions are the primary evidence source.
- A rule never returns a negative claim when its prerequisites are absent; it returns `unavailable` or `limited`.
- Pipeline names such as `bm25` and `dense` are not evidence.
- Every finding carries method ID/version, evidence class, cutoff, supporting trace/operator/document IDs, limitations, and unavailable reason.
- `ranking_failure` means a relevant document remains in final output but ranks below an explicit requested cutoff `k`.
- Production quality remains unavailable unless ground truth is explicitly joined.
- The host application and telemetry behavior must not be changed by diagnostic computation.
- Every meaningful behavior change adds one concise `[Unreleased]` entry to `CHANGELOG.md`.

---

### Task 1: Define the typed diagnostic contract and rule protocol

**Files:**
- Create: `retrieval_observatory/diagnostics/__init__.py`
- Create: `retrieval_observatory/diagnostics/model.py`
- Create: `retrieval_observatory/diagnostics/rules.py`
- Test: `tests/unit/test_diagnostic_model.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `RetrievalTrace`, qrels, corpus identity, and evaluation cutoff.
- Produces: `DiagnosticContext`, `DiagnosticFinding`, `DiagnosticEvidence`, `DiagnosticRule`, and `RuleResult`.

- [ ] **Step 1: Write failing model tests**

```python
from retrieval_observatory.diagnostics.model import (
    DiagnosticEvidence,
    DiagnosticFinding,
    FindingAvailability,
)


def test_finding_roundtrip_preserves_evidence_contract() -> None:
    finding = DiagnosticFinding(
        label="fusion_loss",
        availability=FindingAvailability.SUPPORTED,
        evidence=DiagnosticEvidence(
            evidence_class="measured_candidate_transition",
            method_id="candidate_loss",
            method_version="1.0",
            trace_ids=("trace-1",),
            operator_ids=("fuse",),
            document_ids=("relevant-1",),
            cutoff=10,
            limitations=(),
        ),
    )
    assert DiagnosticFinding.from_dict(finding.to_dict()) == finding


def test_unavailable_finding_requires_reason() -> None:
    with pytest.raises(ValueError, match="unavailable_reason"):
        DiagnosticFinding(label="ranking_failure", availability=FindingAvailability.UNAVAILABLE)
```

- [ ] **Step 2: Verify the package does not exist**

Run: `pytest tests/unit/test_diagnostic_model.py -v`

Expected: collection fails with `ModuleNotFoundError: retrieval_observatory.diagnostics`.

- [ ] **Step 3: Implement immutable typed findings**

```python
class FindingAvailability(str, Enum):
    SUPPORTED = "supported"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    NOT_OBSERVED = "not_observed"


@dataclass(frozen=True)
class DiagnosticEvidence:
    evidence_class: str
    method_id: str
    method_version: str
    trace_ids: tuple[str, ...] = ()
    operator_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    cutoff: int | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticFinding:
    label: str
    availability: FindingAvailability
    evidence: DiagnosticEvidence | None = None
    unavailable_reason: str | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)
```

Validation must require evidence for `SUPPORTED`/`LIMITED`, require `unavailable_reason` for `UNAVAILABLE`, and reject evidence that references unknown trace/operator IDs when built through the engine.

- [ ] **Step 4: Define the rule protocol**

```python
class DiagnosticRule(Protocol):
    label: str
    method_id: str
    method_version: str

    def evaluate(self, context: DiagnosticContext) -> DiagnosticFinding: ...
```

`DiagnosticContext` contains the trace, relevant document IDs, optional corpus document IDs, cutoff, candidate histories, and capture completeness flags. It exposes no mutable store object.

- [ ] **Step 5: Run model tests**

Run: `pytest tests/unit/test_diagnostic_model.py -v`

Expected: all pass, including round-trip and invalid-state tests.

- [ ] **Step 6: Record and commit the contract**

Add under `CHANGELOG.md` → `[Unreleased]` → `Added`:

```markdown
- `diagnostics/model.py` — add versioned evidence contracts for supported, limited, unavailable, and not-observed retrieval findings.
```

```bash
git add retrieval_observatory/diagnostics tests/unit/test_diagnostic_model.py CHANGELOG.md
git commit -m "feat: define typed diagnostic evidence"
```

### Task 2: Build branch-aware candidate histories from unified traces

**Files:**
- Move/Modify: `retrieval_observatory/tracing/candidate_history.py` → `retrieval_observatory/diagnostics/history.py`
- Test: `tests/unit/test_candidate_history.py`
- Test: `tests/unit/test_diagnostic_unavailable_evidence.py`

**Interfaces:**
- Consumes: `OperatorSpan.input_groups`, outputs, status, gate values, capture metadata.
- Produces: `CandidateHistoryIndex.build(trace)`, `CandidateEvent`, and completeness flags.

- [ ] **Step 1: Add branch and incomplete-capture tests**

```python
def test_history_preserves_branch_and_drop_reason(hybrid_trace) -> None:
    history = CandidateHistoryIndex.build(hybrid_trace).for_document("relevant-1")
    assert history.event("dense").state == "emitted"
    assert history.event("bm25").state == "absent"
    assert history.event("fuse").input_parents == ("dense",)
    assert history.event("temporal_filter").drop_reason == "outside_time_window"


def test_truncated_payload_marks_history_incomplete(truncated_trace) -> None:
    index = CandidateHistoryIndex.build(truncated_trace)
    assert index.complete is False
    assert index.limitations == ("candidate_payload_truncated",)
```

- [ ] **Step 2: Confirm current history lacks grouped-parent completeness**

Run: `pytest tests/unit/test_candidate_history.py tests/unit/test_diagnostic_unavailable_evidence.py -v`

Expected: new cases fail because current events flatten parents and do not expose capture completeness.

- [ ] **Step 3: Define the history structures**

```python
@dataclass(frozen=True)
class CandidateEvent:
    op_id: str
    op_type: str
    state: Literal["input", "emitted", "removed", "absent", "skipped", "unknown"]
    input_parents: tuple[str, ...] = ()
    rank: int | None = None
    score: float | None = None
    drop_reason: str | None = None


@dataclass(frozen=True)
class CandidateHistoryIndex:
    by_document: Mapping[str, tuple[CandidateEvent, ...]]
    complete: bool
    limitations: tuple[str, ...]
```

Build histories in topological span order. Use parent groups and explicit status/drop reasons; never infer branch identity from pipeline names.

- [ ] **Step 4: Mark incomplete evidence**

Set `complete=False` when candidate capture is sampled, truncated, missing from a fired non-source span, or structurally invalid. Preserve the exact reason for rule prerequisites.

- [ ] **Step 5: Run history tests**

Run: `pytest tests/unit/test_candidate_history.py tests/unit/test_candidate_identity_contract.py tests/unit/test_diagnostic_unavailable_evidence.py -v`

Expected: all pass with branch-specific histories and completeness reasons.

- [ ] **Step 6: Commit trace-native histories**

```bash
git add retrieval_observatory/diagnostics/history.py retrieval_observatory/tracing/candidate_history.py tests/unit/test_candidate_history.py tests/unit/test_candidate_identity_contract.py tests/unit/test_diagnostic_unavailable_evidence.py
git commit -m "refactor: build branch-aware candidate histories"
```

### Task 3: Implement identity, source, branch, and gate diagnostic rules

**Files:**
- Create: `retrieval_observatory/diagnostics/identity_rules.py`
- Create: `retrieval_observatory/diagnostics/routing_rules.py`
- Test: `tests/unit/test_diagnostic_identity_rules.py`
- Test: `tests/unit/test_diagnostic_routing_rules.py`

**Interfaces:**
- Consumes: `DiagnosticContext` and `CandidateHistoryIndex`.
- Produces rules `QrelAbsentFromCorpusRule`, `SourceMissRule`, `BranchSpecificMissRule`, and `GateExclusionRule`.

- [ ] **Step 1: Write failing identity and routing cases**

```python
def test_source_miss_requires_relevant_doc_absent_from_all_sources(context_factory) -> None:
    context = context_factory(relevant={"r1"}, source_outputs={"bm25": (), "dense": ()})
    finding = SourceMissRule().evaluate(context)
    assert finding.availability == FindingAvailability.SUPPORTED
    assert finding.evidence.operator_ids == ("bm25", "dense")


def test_gate_exclusion_identifies_relevant_skipped_branch(context_factory) -> None:
    context = context_factory(
        relevant={"r1"},
        counterfactual_branch_outputs={"temporal": {"r1"}},
        selected_route="generic",
    )
    finding = GateExclusionRule().evaluate(context)
    assert finding.label == "gate_exclusion"
    assert finding.details["selected_route"] == "generic"
```

Include qrel absent from corpus, relevant only in secondary branch, no labels, and missing skipped-span evidence.

- [ ] **Step 2: Run tests to confirm rules are absent**

Run: `pytest tests/unit/test_diagnostic_identity_rules.py tests/unit/test_diagnostic_routing_rules.py -v`

Expected: collection or imports fail for the new rule modules.

- [ ] **Step 3: Implement explicit prerequisites**

```python
class SourceMissRule:
    label = "source_miss"
    method_id = "candidate_transition"
    method_version = "1.0"

    def evaluate(self, context: DiagnosticContext) -> DiagnosticFinding:
        if not context.relevant_document_ids:
            return unavailable(self, "ground_truth_missing")
        if not context.history.complete:
            return unavailable(self, "candidate_capture_incomplete", context.history.limitations)
        source_ids = context.trace.operator_ids(op_type="SOURCE")
        missed = context.relevant_document_ids - context.output_documents(source_ids)
        return supported(self, missed, operator_ids=source_ids) if missed else not_observed(self)
```

Gate exclusion is supported only when the relevant document's availability in the skipped route is measured or exactly replayed. Otherwise return limited/unavailable rather than claiming a counterfactual.

- [ ] **Step 4: Run identity/routing tests**

Run: `pytest tests/unit/test_diagnostic_identity_rules.py tests/unit/test_diagnostic_routing_rules.py tests/unit/test_zero_label.py -v`

Expected: all pass; unlabeled cases never emit quality failures.

- [ ] **Step 5: Commit identity and routing rules**

```bash
git add retrieval_observatory/diagnostics/identity_rules.py retrieval_observatory/diagnostics/routing_rules.py tests/unit/test_diagnostic_identity_rules.py tests/unit/test_diagnostic_routing_rules.py tests/unit/test_zero_label.py
git commit -m "feat: diagnose retrieval identity and routing failures"
```

### Task 4: Implement fusion, filter, rerank, truncation, and final-ranking rules

**Files:**
- Create: `retrieval_observatory/diagnostics/transition_rules.py`
- Test: `tests/unit/test_diagnostic_transition_rules.py`
- Delete/Modify: `retrieval_observatory/metrics/diagnostics.py`

**Interfaces:**
- Consumes: relevant IDs, explicit cutoff, operator-specific candidate transitions.
- Produces: `FusionLossRule`, `FilterLossRule`, `RerankerLossRule`, `TruncationLossRule`, and `FinalRankingFailureRule`.

- [ ] **Step 1: Write a complete transition-rule truth table**

```python
@pytest.mark.parametrize(
    ("rule", "fixture_name", "expected"),
    [
        (FusionLossRule(), "fusion_drops_relevant", "fusion_loss"),
        (FilterLossRule(), "filter_drops_relevant", "filter_loss"),
        (RerankerLossRule(), "reranker_drops_relevant", "reranker_loss"),
        (TruncationLossRule(), "topk_truncates_relevant", "truncation_loss"),
        (FinalRankingFailureRule(), "relevant_at_rank_11_k_10", "ranking_failure"),
    ],
)
def test_transition_rule(rule, fixture_name, expected, request) -> None:
    context = request.getfixturevalue(fixture_name)
    finding = rule.evaluate(context)
    assert finding.label == expected
    assert finding.availability == FindingAvailability.SUPPORTED
```

Add negative cases, duplicate IDs, final output already truncated to `k`, and missing pre-transition candidates.

- [ ] **Step 2: Prove the old `ranking_failure` condition is wrong**

Run: `pytest tests/unit/test_diagnostic_transition_rules.py -v`

Expected: failures show no trace-native rules and the legacy condition cannot label rank 11 at `k=10` correctly.

- [ ] **Step 3: Implement one shared transition-loss helper**

```python
def relevant_removed_by_operator(context: DiagnosticContext, op_type: str) -> tuple[str, ...]:
    removed: set[str] = set()
    for span in context.trace.spans_of_type(op_type):
        input_ids = {candidate.doc_id for group in span.input_groups.values() for candidate in group}
        output_ids = {candidate.doc_id for candidate in span.outputs}
        removed.update((input_ids - output_ids) & context.relevant_document_ids)
    return tuple(sorted(removed))
```

Use the helper for fusion/filter/rerank only when the operator-specific prerequisites hold. Truncation requires explicit truncation metadata. Do not classify an arbitrary drop as truncation.

- [ ] **Step 4: Implement the corrected final-ranking definition**

```python
class FinalRankingFailureRule:
    def evaluate(self, context: DiagnosticContext) -> DiagnosticFinding:
        if context.cutoff is None:
            return unavailable(self, "evaluation_cutoff_missing")
        if context.final_output_pretruncated_at == context.cutoff:
            return unavailable(self, "pre_truncation_ranking_not_captured")
        below_cutoff = {
            candidate.doc_id
            for candidate in context.final_candidates
            if candidate.rank > context.cutoff
        } & context.relevant_document_ids
        return supported(self, below_cutoff, cutoff=context.cutoff) if below_cutoff else not_observed(self)
```

Remove `build_query_diagnostics()` and pipeline-name substring heuristics once the engine cutover in Task 5 lands.

- [ ] **Step 5: Run transition and regression tests**

Run: `pytest tests/unit/test_diagnostic_transition_rules.py tests/unit/test_diagnostic_evidence_contract.py tests/unit/test_hybrid_fanin.py -v`

Expected: all pass; rank-below-`k` is distinguished from removal and unavailable pre-truncation evidence.

- [ ] **Step 6: Commit transition rules**

```bash
git add retrieval_observatory/diagnostics/transition_rules.py retrieval_observatory/metrics/diagnostics.py tests/unit/test_diagnostic_transition_rules.py tests/unit/test_diagnostic_evidence_contract.py tests/unit/test_hybrid_fanin.py
git commit -m "fix: make candidate-loss diagnostics trace-native"
```

### Task 5: Build the diagnostic engine and persist versioned findings

**Files:**
- Create: `retrieval_observatory/diagnostics/engine.py`
- Modify: `retrieval_observatory/store/base.py`
- Modify: `retrieval_observatory/store/sqlite.py`
- Modify: `retrieval_observatory/store/postgres.py`
- Modify: `retrieval_observatory/runner/execute.py`
- Test: `tests/unit/test_diagnostic_engine.py`
- Test: `tests/unit/test_diagnostic_store_contract.py`

**Interfaces:**
- Consumes: trace, labels, corpus identity, cutoff, registered rules.
- Produces: `DiagnosticEngine.evaluate(context) -> tuple[DiagnosticFinding, ...]`, `save_diagnostics`, and `query_diagnostics`.

- [ ] **Step 1: Add engine ordering and store parity tests**

```python
def test_engine_returns_one_result_per_registered_rule(context) -> None:
    engine = DiagnosticEngine.default()
    findings = engine.evaluate(context)
    assert tuple(f.label for f in findings) == engine.rule_labels
    assert all(f.availability for f in findings)


@pytest.mark.parametrize("store_fixture", ["sqlite_store", "postgres_store"])
async def test_diagnostic_roundtrip(store_fixture, request, diagnostic_findings) -> None:
    store = request.getfixturevalue(store_fixture)
    await store.save_diagnostics("run-1", "query-1", diagnostic_findings)
    restored = await store.query_diagnostics(run_id="run-1", query_id="query-1")
    assert restored == diagnostic_findings
```

- [ ] **Step 2: Run tests to verify missing engine/store methods**

Run: `pytest tests/unit/test_diagnostic_engine.py tests/unit/test_diagnostic_store_contract.py -v`

Expected: failures for missing `DiagnosticEngine` and typed store methods.

- [ ] **Step 3: Implement a deterministic rule registry**

```python
class DiagnosticEngine:
    def __init__(self, rules: Sequence[DiagnosticRule]):
        self._rules = tuple(rules)

    @classmethod
    def default(cls) -> "DiagnosticEngine":
        return cls((
            QrelAbsentFromCorpusRule(), SourceMissRule(), BranchSpecificMissRule(),
            GateExclusionRule(), FusionLossRule(), FilterLossRule(),
            RerankerLossRule(), TruncationLossRule(), FinalRankingFailureRule(),
        ))

    def evaluate(self, context: DiagnosticContext) -> tuple[DiagnosticFinding, ...]:
        return tuple(rule.evaluate(context) for rule in self._rules)
```

Do not drop `NOT_OBSERVED` or `UNAVAILABLE` results; they are necessary to explain which conclusions were evaluated and why others are absent.

- [ ] **Step 4: Persist JSON plus indexed finding fields**

Store run/query/trace scope, label, availability, method ID/version, evidence class, and the complete JSON. Use one shared store contract test for SQLite and PostgreSQL.

- [ ] **Step 5: Cut runner execution over to trace-native diagnosis**

```python
trace = await pipeline.execute(query)
await store.save_trace(trace)
context = await diagnostic_context_for_trace(trace, labels=labels, corpus=corpus, cutoff=config.k)
findings = DiagnosticEngine.default().evaluate(context)
await store.save_diagnostics(run_id, query.query_id, findings)
```

Delete the legacy call that diagnoses `PipelineResult` snapshots.

- [ ] **Step 6: Run engine, store, and runner tests**

Run: `pytest tests/unit/test_diagnostic_engine.py tests/unit/test_diagnostic_store_contract.py tests/unit/test_store_contract.py tests/integration/test_reference_architecture.py -v`

Expected: all pass with identical SQLite/PostgreSQL results.

- [ ] **Step 7: Commit the diagnostic engine cutover**

```bash
git add retrieval_observatory/diagnostics/engine.py retrieval_observatory/store retrieval_observatory/runner/execute.py tests/unit/test_diagnostic_engine.py tests/unit/test_diagnostic_store_contract.py tests/unit/test_store_contract.py tests/integration/test_reference_architecture.py
git commit -m "refactor: persist trace-native diagnostic findings"
```

### Task 6: Make query evidence and recommendations consume stored findings

**Files:**
- Modify: `retrieval_observatory/evidence/query.py`
- Modify: `retrieval_observatory/advisor/recommend.py` (renamed public-neutral findings module by Workstream 8)
- Modify: `retrieval_observatory/dashboard/api.py`
- Test: `tests/unit/test_query_evidence_scope.py`
- Test: `tests/unit/test_advisor.py`
- Test: `tests/unit/test_production_finding_contract.py`

**Interfaces:**
- Consumes: stored `DiagnosticFinding` records.
- Produces: API/UI finding payloads without alternate label inference.

- [ ] **Step 1: Add a no-reinterpretation contract test**

```python
async def test_query_api_preserves_stored_diagnostic_evidence(client, seeded_finding) -> None:
    response = await client.get("/dbs/results/runs/run-1/queries/q-1/evidence")
    finding = response.json()["diagnostics"][0]
    assert finding["method_id"] == seeded_finding.evidence.method_id
    assert finding["method_version"] == seeded_finding.evidence.method_version
    assert finding["availability"] == seeded_finding.availability.value
    assert finding["limitations"] == list(seeded_finding.evidence.limitations)
```

Add a recommendation test proving unavailable/limited findings cannot produce a high-confidence causal recommendation.

- [ ] **Step 2: Run consumer tests**

Run: `pytest tests/unit/test_query_evidence_scope.py tests/unit/test_advisor.py tests/unit/test_production_finding_contract.py -v`

Expected: new assertions fail because consumers currently reconstruct or flatten diagnostic evidence.

- [ ] **Step 3: Serialize the stored contract directly**

```python
def diagnostic_payload(finding: DiagnosticFinding) -> dict[str, object]:
    return finding.to_dict()
```

Query evidence may add links and presentation labels but must not change availability, method, support, or limitations.

- [ ] **Step 4: Gate recommendations by evidence**

```python
if finding.availability != FindingAvailability.SUPPORTED:
    return Recommendation.unavailable(
        source_label=finding.label,
        reason=finding.unavailable_reason or "diagnostic_evidence_limited",
    )
```

Recommendations include source finding IDs and compatible method versions.

- [ ] **Step 5: Run consumer tests**

Run: `pytest tests/unit/test_query_evidence_scope.py tests/unit/test_advisor.py tests/unit/test_production_finding_contract.py -v`

Expected: all pass; no consumer upgrades evidence strength.

- [ ] **Step 6: Commit evidence consumers**

```bash
git add retrieval_observatory/evidence/query.py retrieval_observatory/advisor/recommend.py retrieval_observatory/dashboard/api.py tests/unit/test_query_evidence_scope.py tests/unit/test_advisor.py tests/unit/test_production_finding_contract.py
git commit -m "fix: preserve diagnostic evidence across consumers"
```

### Task 7: Add the adversarial hybrid/gated diagnostic suite

**Files:**
- Create: `tests/fixtures/diagnostic_traces.py`
- Create: `tests/integration/test_diagnostics_hybrid_dag.py`
- Modify: `tests/unit/test_diagnostic_evidence_contract.py`

**Interfaces:**
- Consumes: all diagnostic rules and unified traces.
- Produces: regression protection for every supported and unavailable outcome.

- [ ] **Step 1: Build explicit trace fixtures**

Create fixture builders for:

```python
TRACE_CASES = (
    "two_source_overlap",
    "relevant_secondary_branch_only",
    "relevant_branch_skipped_by_gate",
    "fusion_removes_relevant",
    "filter_removes_relevant",
    "reranker_removes_relevant",
    "relevant_below_cutoff",
    "final_output_pretruncated",
    "duplicate_document_ids",
    "conditional_operator_skipped",
    "operator_error",
    "operator_timeout",
    "candidate_payload_truncated",
    "missing_qrels",
    "qrel_absent_from_corpus",
)
```

Every builder must declare expected findings and expected unavailable reasons.

- [ ] **Step 2: Add the table-driven integration test**

```python
@pytest.mark.parametrize("case_name", TRACE_CASES)
def test_diagnostic_case(case_name, diagnostic_case) -> None:
    case = diagnostic_case(case_name)
    findings = {f.label: f for f in DiagnosticEngine.default().evaluate(case.context)}
    for label, availability in case.expected_availability.items():
        assert findings[label].availability.value == availability
    for label, reason in case.expected_unavailable_reasons.items():
        assert findings[label].unavailable_reason == reason
```

- [ ] **Step 3: Run the adversarial suite**

Run: `pytest tests/integration/test_diagnostics_hybrid_dag.py -v`

Expected: all cases pass; no unsupported causal label appears.

- [ ] **Step 4: Run the complete diagnostic regression set**

Run: `pytest tests/unit/test_diagnostic_*.py tests/unit/test_candidate_history.py tests/unit/test_hybrid_fanin.py tests/unit/test_zero_label.py tests/integration/test_diagnostics_hybrid_dag.py -v`

Expected: all pass.

- [ ] **Step 5: Commit adversarial fixtures**

```bash
git add tests/fixtures/diagnostic_traces.py tests/integration/test_diagnostics_hybrid_dag.py tests/unit/test_diagnostic_evidence_contract.py
git commit -m "test: cover hybrid diagnostic evidence boundaries"
```

## Workstream completion gate

Run:

```bash
pytest tests/unit/test_diagnostic_*.py tests/unit/test_candidate_history.py tests/unit/test_candidate_identity_contract.py tests/unit/test_hybrid_fanin.py tests/unit/test_query_evidence_scope.py tests/unit/test_advisor.py tests/unit/test_production_finding_contract.py -v
pytest tests/integration/test_diagnostics_hybrid_dag.py tests/integration/test_reference_architecture.py -v
```

Expected: all pass. `retrieval_observatory/metrics/diagnostics.py` contains no snapshot-order or pipeline-name diagnosis path, and `rg -n "ranking_failure" retrieval_observatory tests` finds only the corrected trace-native rule, factual UI copy, and its tests.
