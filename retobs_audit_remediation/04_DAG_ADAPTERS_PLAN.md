# Faithful DAG Semantics and Framework Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make configured and observed retrieval graphs preserve stable operator identity, real parentage, parent-grouped candidates, conditional execution, and operator-specific behavior across native, LangChain, LlamaIndex, Haystack, DSPy, and OpenAI Agents pipelines.

**Architecture:** Replace the generic “source/fuse/otherwise-rerank” executor with discriminated operator specifications and an executor registry. Preserve candidate inputs by parent throughout trace serialization, and resolve framework events through the integration manifest rather than random IDs or previous-span ordering.

**Tech Stack:** Python 3.10+, Pydantic/config dataclasses already used by retobs, asyncio, pytest, existing adapter protocols, unified `RetrievalTrace` and `IntegrationManifest` contracts from Workstreams 1-2.

## Global Constraints

- One public trace model exists; do not add V1/V2 branches.
- The host application remains the pipeline runtime; framework instrumentation observes rather than re-orchestrates it.
- Operator identity must be deterministic across processes and ordinary source edits.
- Parent relationships come from a manifest or framework-native run relationships, never list position.
- Unsupported executable semantics fail validation instead of falling back to reranking.
- Missing candidate or topology evidence must remain explicitly unavailable.
- Every meaningful structural change adds one concise `[Unreleased]` line to `CHANGELOG.md`.
- No deprecated commands, aliases, product names, or compatibility shims may be introduced.

---

### Task 1: Consolidate the graph schema into discriminated operator specifications

**Files:**
- Create: `retrieval_observatory/config/operators.py`
- Modify: `retrieval_observatory/config/schema.py`
- Delete: `retrieval_observatory/config/dag_schema.py`
- Modify: `retrieval_observatory/pipeline/factory.py`
- Test: `tests/unit/test_operator_schema.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `IntegrationManifest.operators` from Workstream 1.
- Produces: `OperatorSpec`, `SourceSpec`, `FuseSpec`, `RerankSpec`, `FilterSpec`, `GateSpec`, `BoostSpec`, `ExpandSpec`, `TransformSpec`, `GenerateSpec`, and `PipelineGraphSpec`.

- [ ] **Step 1: Write failing schema tests**

```python
import pytest

from retrieval_observatory.config.operators import parse_pipeline_graph


def test_fuse_requires_two_parents() -> None:
    raw = {
        "pipeline_id": "hybrid",
        "operators": [
            {"op_id": "dense", "op_type": "SOURCE", "parents": [], "adapter": "dense"},
            {"op_id": "fuse", "op_type": "FUSE", "parents": ["dense"], "method": "rrf"},
        ],
        "final_operator_ids": ["fuse"],
    }
    with pytest.raises(ValueError, match="FUSE requires at least two parents"):
        parse_pipeline_graph(raw)


def test_filter_does_not_accept_rerank_configuration() -> None:
    raw = {
        "pipeline_id": "filtered",
        "operators": [
            {"op_id": "source", "op_type": "SOURCE", "parents": [], "adapter": "dense"},
            {"op_id": "filter", "op_type": "FILTER", "parents": ["source"], "adapter": "reranker"},
        ],
        "final_operator_ids": ["filter"],
    }
    with pytest.raises(ValueError, match="FILTER requires a predicate executor"):
        parse_pipeline_graph(raw)
```

- [ ] **Step 2: Confirm the new contract is absent**

Run: `pytest tests/unit/test_operator_schema.py -v`

Expected: collection fails with `ModuleNotFoundError: retrieval_observatory.config.operators`.

- [ ] **Step 3: Add the discriminated operator contracts**

```python
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Union


@dataclass(frozen=True)
class OperatorBase:
    op_id: str
    parents: tuple[str, ...]
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSpec(OperatorBase):
    op_type: Literal["SOURCE"] = "SOURCE"
    adapter: str = ""


@dataclass(frozen=True)
class FuseSpec(OperatorBase):
    op_type: Literal["FUSE"] = "FUSE"
    method: Literal["rrf"] = "rrf"
    top_k: int = 10


@dataclass(frozen=True)
class RerankSpec(OperatorBase):
    op_type: Literal["RERANK"] = "RERANK"
    adapter: str = ""
    top_k: int = 10


@dataclass(frozen=True)
class FilterSpec(OperatorBase):
    op_type: Literal["FILTER"] = "FILTER"
    predicate: str = ""


@dataclass(frozen=True)
class GateSpec(OperatorBase):
    op_type: Literal["GATE"] = "GATE"
    router: str = ""
    branches: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


OperatorSpec = Union[SourceSpec, FuseSpec, RerankSpec, FilterSpec, GateSpec]


@dataclass(frozen=True)
class PipelineGraphSpec:
    pipeline_id: str
    operators: tuple[OperatorSpec, ...]
    final_operator_ids: tuple[str, ...]
```

Implement equivalent typed specifications for `BOOST`, `EXPAND`, `TRANSFORM`, and `GENERATE`. `parse_pipeline_graph(raw)` must reject duplicate IDs, unknown parents, cycles, invalid parent counts, missing executors, and unknown final operators.

- [ ] **Step 4: Make the factory accept only `PipelineGraphSpec`**

```python
def build_dag_pipeline(config: PipelineGraphSpec, adapters: AdapterRegistry) -> DagPipeline:
    validate_adapter_bindings(config, adapters)
    return DagPipeline(graph=config, adapters=adapters, executors=default_operator_executors())
```

Remove `_infer_op_type()` and the separate `DagPipelineConfig` path. Update imports to the sole schema.

- [ ] **Step 5: Run schema and factory tests**

Run: `pytest tests/unit/test_operator_schema.py tests/unit/test_factory.py tests/unit/test_config.py -v`

Expected: all tests pass; invalid graphs fail during parsing rather than execution.

- [ ] **Step 6: Record and commit the graph-schema change**

Add under `CHANGELOG.md` → `[Unreleased]` → `Changed`:

```markdown
- `config/operators.py` — replace generic DAG nodes with validated operator-specific graph specifications.
```

```bash
git add retrieval_observatory/config retrieval_observatory/pipeline/factory.py tests/unit/test_operator_schema.py tests/unit/test_factory.py tests/unit/test_config.py CHANGELOG.md
git commit -m "refactor: validate operator-specific DAG schemas"
```

### Task 2: Preserve parent-grouped candidates in the sole trace model

**Files:**
- Modify: `retrieval_observatory/tracing/model.py` (created as the sole model by Workstream 2)
- Modify: `retrieval_observatory/tracing/candidates.py`
- Modify: `retrieval_observatory/pipeline/graph_projection.py`
- Test: `tests/unit/test_parent_grouped_candidates.py`

**Interfaces:**
- Consumes: sole `Candidate` and `OperatorSpan` models from Workstream 2.
- Produces: `OperatorSpan.input_groups: dict[str, tuple[Candidate, ...]]` and `build_candidate_transition(...) -> CandidateTransition`.

- [ ] **Step 1: Add a failing round-trip test**

```python
from retrieval_observatory.tracing.model import Candidate, OperatorSpan


def test_operator_span_roundtrip_preserves_parent_groups() -> None:
    sparse = Candidate(doc_id="s1", rank=1, score=4.0, origin_op_ids=("bm25",))
    dense = Candidate(doc_id="d1", rank=1, score=0.9, origin_op_ids=("dense",))
    span = OperatorSpan(
        op_id="fuse",
        op_type="FUSE",
        op_name="fusion",
        parent_ids=("bm25", "dense"),
        input_groups={"bm25": (sparse,), "dense": (dense,)},
        outputs=(sparse, dense),
        status="FIRED",
        latency_ms=1.0,
    )
    restored = OperatorSpan.from_dict(span.to_dict())
    assert tuple(restored.input_groups) == ("bm25", "dense")
    assert restored.input_groups["dense"][0].doc_id == "d1"
```

- [ ] **Step 2: Verify flattened inputs lose the required evidence**

Run: `pytest tests/unit/test_parent_grouped_candidates.py -v`

Expected: FAIL because `OperatorSpan` has no serialized `input_groups` field.

- [ ] **Step 3: Add `CandidateTransition` and grouped serialization**

```python
@dataclass(frozen=True)
class CandidateTransition:
    input_groups: dict[str, tuple[Candidate, ...]]
    outputs: tuple[Candidate, ...]


def build_candidate_transition(
    *,
    input_groups: Mapping[str, Sequence[Candidate]],
    output_items: Sequence[object],
    op_id: str,
    op_type: str,
) -> CandidateTransition:
    normalized_inputs = {parent: tuple(items) for parent, items in input_groups.items()}
    outputs = tuple(to_candidates(output_items, op_id=op_id, op_type=op_type))
    return CandidateTransition(input_groups=normalized_inputs, outputs=outputs)
```

Store `input_groups` as the canonical form. If a flattened `inputs` convenience property remains, compute it from parent order and do not serialize it separately.

- [ ] **Step 4: Update graph projection to use grouped parents**

```python
input_count = sum(len(candidates) for candidates in span.input_groups.values())
parent_counts = {parent_id: len(candidates) for parent_id, candidates in span.input_groups.items()}
```

Expose `parent_candidate_counts` in graph-node evidence so fan-in is auditable.

- [ ] **Step 5: Run transition and graph contracts**

Run: `pytest tests/unit/test_parent_grouped_candidates.py tests/unit/test_candidate_identity_contract.py tests/unit/test_pipeline_graph_contract_v2.py -v`

Expected: all pass; serialization preserves branch identity.

- [ ] **Step 6: Commit parent-group preservation**

```bash
git add retrieval_observatory/tracing/model.py retrieval_observatory/tracing/candidates.py retrieval_observatory/pipeline/graph_projection.py tests/unit/test_parent_grouped_candidates.py tests/unit/test_candidate_identity_contract.py tests/unit/test_pipeline_graph_contract_v2.py
git commit -m "feat: preserve parent-grouped candidate transitions"
```

### Task 3: Replace generic DAG execution with typed operator executors

**Files:**
- Create: `retrieval_observatory/pipeline/executors.py`
- Modify: `retrieval_observatory/pipeline/dag.py`
- Modify: `retrieval_observatory/adapters/base.py`
- Test: `tests/unit/test_operator_execution_semantics.py`

**Interfaces:**
- Consumes: `OperatorSpec`, `CandidateTransition`, `ExecutionContext`.
- Produces: `OperatorExecutor.execute(spec, input_groups, context) -> OperatorExecutionResult` and `default_operator_executors()`.

- [ ] **Step 1: Write failing multi-parent and unsupported-operation tests**

```python
import pytest


@pytest.mark.asyncio
async def test_filter_receives_all_declared_parent_groups(filter_pipeline, recording_filter) -> None:
    trace = await filter_pipeline.run("recent policy")
    assert recording_filter.parent_ids == ("bm25", "dense")
    assert {candidate.doc_id for candidate in recording_filter.received} == {"b1", "d1"}
    assert trace.span("recent_only").op_type == "FILTER"


def test_missing_filter_executor_fails_at_build_time(filter_graph, adapters) -> None:
    with pytest.raises(ValueError, match="No FILTER executor registered"):
        build_dag_pipeline(filter_graph, adapters)
```

- [ ] **Step 2: Confirm current behavior uses only the first parent**

Run: `pytest tests/unit/test_operator_execution_semantics.py -v`

Expected: multi-parent test fails because `dag.py` passes only `node.inputs[0]` to `rerank`.

- [ ] **Step 3: Define the executor protocol and result**

```python
@dataclass(frozen=True)
class OperatorExecutionResult:
    outputs: tuple[Candidate, ...]
    status: Literal["FIRED", "SKIPPED_BY_GATE", "ERROR", "TIMEOUT"] = "FIRED"
    gate_values: Mapping[str, object] = field(default_factory=dict)
    drop_reasons: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)


class OperatorExecutor(Protocol):
    async def execute(
        self,
        spec: OperatorSpec,
        input_groups: Mapping[str, tuple[Candidate, ...]],
        context: ExecutionContext,
    ) -> OperatorExecutionResult: ...
```

Implement explicit executors for every declared operator type. `RERANK` may combine multiple parent groups only through the graph's declared merge policy; it must not silently discard a parent.

- [ ] **Step 4: Make `DagPipeline` dispatch by `op_type`**

```python
executor = self.executors.get(spec.op_type)
if executor is None:
    raise OperatorConfigurationError(f"No {spec.op_type} executor registered for {spec.op_id}")
result = await executor.execute(spec, input_groups, context)
transition = build_candidate_transition(
    input_groups=input_groups,
    output_items=result.outputs,
    op_id=spec.op_id,
    op_type=spec.op_type,
)
```

Remove the `if FUSE / elif no inputs / else rerank` fallback.

- [ ] **Step 5: Run native DAG execution tests**

Run: `pytest tests/unit/test_operator_execution_semantics.py tests/unit/test_dag_pipeline.py tests/unit/test_dag_execution_contract.py -v`

Expected: all pass; each operator uses its declared executor and all parents remain visible.

- [ ] **Step 6: Commit typed execution**

```bash
git add retrieval_observatory/pipeline/executors.py retrieval_observatory/pipeline/dag.py retrieval_observatory/adapters/base.py tests/unit/test_operator_execution_semantics.py tests/unit/test_dag_pipeline.py tests/unit/test_dag_execution_contract.py
git commit -m "refactor: execute DAG operators by declared semantics"
```

### Task 4: Record gate decisions, skipped branches, and candidate drop reasons

**Files:**
- Modify: `retrieval_observatory/pipeline/executors.py`
- Modify: `retrieval_observatory/pipeline/dag.py`
- Modify: `retrieval_observatory/tracing/candidates.py`
- Test: `tests/integration/test_gated_hybrid_dag.py`

**Interfaces:**
- Consumes: `GateSpec.branches`, operator execution result.
- Produces: explicit `SKIPPED_BY_GATE` spans and candidate `drop_reason` events.

- [ ] **Step 1: Add a gated hybrid fixture test**

```python
@pytest.mark.asyncio
async def test_temporal_route_records_selected_and_skipped_branches(gated_pipeline) -> None:
    trace = await gated_pipeline.run("policy changes after 2025", query_id="q-temporal")
    assert trace.span("intent_gate").gate_values["selected_route"] == "temporal"
    assert trace.span("temporal_filter").status == "FIRED"
    assert trace.span("generic_reranker").status == "SKIPPED_BY_GATE"
    assert trace.span("generic_reranker").parent_ids == ("intent_gate",)
```

Add cases for filter removal, timeout, router error, and two queries that exercise every declared branch.

- [ ] **Step 2: Verify skipped branches are currently omitted**

Run: `pytest tests/integration/test_gated_hybrid_dag.py -v`

Expected: FAIL because unselected operators do not emit spans.

- [ ] **Step 3: Emit explicit conditional spans**

```python
def skipped_span(spec: OperatorSpec, decision: GateDecision) -> OperatorSpan:
    return OperatorSpan(
        op_id=spec.op_id,
        op_type=spec.op_type,
        op_name=spec.op_id,
        parent_ids=spec.parents,
        input_groups={},
        outputs=(),
        status="SKIPPED_BY_GATE",
        latency_ms=0.0,
        gate_values={"gate_op_id": decision.gate_op_id, "selected_route": decision.route},
    )
```

Filter and truncation executors must record a stable reason for each removed candidate without changing its document identity.

- [ ] **Step 4: Validate final operators under partial/error execution**

Require every successful trace to identify the actual final operator(s). A trace with an error or timeout may have no final operator, but must state why; do not infer “last appended span.”

- [ ] **Step 5: Run gated and candidate-history tests**

Run: `pytest tests/integration/test_gated_hybrid_dag.py tests/unit/test_candidate_history.py tests/unit/test_hybrid_fanin.py -v`

Expected: all pass, including explicit skipped spans and drop reasons.

- [ ] **Step 6: Commit conditional execution evidence**

```bash
git add retrieval_observatory/pipeline/executors.py retrieval_observatory/pipeline/dag.py retrieval_observatory/tracing/candidates.py tests/integration/test_gated_hybrid_dag.py tests/unit/test_candidate_history.py tests/unit/test_hybrid_fanin.py
git commit -m "feat: trace gate decisions and candidate drops"
```

### Task 5: Add a manifest-aware deterministic operator registry

**Files:**
- Create: `retrieval_observatory/tracing/integrations/operator_registry.py`
- Modify: `retrieval_observatory/tracing/integrations/_duck_typed.py`
- Test: `tests/unit/test_adapter_stable_identity.py`
- Test: `tests/unit/test_adapter_concurrent_parentage.py`

**Interfaces:**
- Consumes: `IntegrationManifest`, framework component path, native event/run ID, native parent run IDs.
- Produces: `OperatorBinding` and `OperatorRegistry.resolve(event) -> ResolvedOperator`.

- [ ] **Step 1: Add stable-identity and concurrency tests**

```python
def test_same_component_resolves_to_same_operator_across_traces(manifest) -> None:
    registry = OperatorRegistry.from_manifest(manifest)
    first = registry.resolve(ComponentEvent(path="retriever.dense", run_id="a", parent_run_ids=("gate-a",)))
    second = registry.resolve(ComponentEvent(path="retriever.dense", run_id="b", parent_run_ids=("gate-b",)))
    assert first.op_id == second.op_id == "dense"


def test_parallel_native_runs_keep_declared_parentage(manifest) -> None:
    registry = OperatorRegistry.from_manifest(manifest)
    dense = registry.resolve(ComponentEvent(path="retriever.dense", run_id="dense-1", parent_run_ids=("gate-1",)))
    sparse = registry.resolve(ComponentEvent(path="retriever.bm25", run_id="bm25-1", parent_run_ids=("gate-1",)))
    assert dense.parent_ids == ("intent_gate",)
    assert sparse.parent_ids == ("intent_gate",)
```

- [ ] **Step 2: Confirm random IDs and previous-span parents fail**

Run: `pytest tests/unit/test_adapter_stable_identity.py tests/unit/test_adapter_concurrent_parentage.py -v`

Expected: tests fail because current adapters generate UUID-suffixed IDs and use the last span.

- [ ] **Step 3: Implement deterministic resolution**

```python
@dataclass(frozen=True)
class ResolvedOperator:
    op_id: str
    op_type: str
    parent_ids: tuple[str, ...]


class OperatorRegistry:
    def resolve(self, event: ComponentEvent) -> ResolvedOperator:
        binding = self._by_component_path.get(event.path)
        if binding is None:
            raise UnmappedOperatorError(event.path)
        return ResolvedOperator(binding.op_id, binding.op_type, binding.parent_ids)
```

Framework run IDs are correlation keys only. They must never become stable operator IDs. Unmapped components are recorded as verification failures, not silently assigned random identities.

- [ ] **Step 4: Remove implicit previous-span behavior from duck wrappers**

Require an explicit registry binding or explicit `op_id` and `parent_ids`. Raise a configuration error during integration verification when neither exists.

- [ ] **Step 5: Run registry tests**

Run: `pytest tests/unit/test_adapter_stable_identity.py tests/unit/test_adapter_concurrent_parentage.py tests/unit/test_framework_adapters.py -v`

Expected: all pass with deterministic IDs and concurrent parentage.

- [ ] **Step 6: Commit operator registry**

```bash
git add retrieval_observatory/tracing/integrations/operator_registry.py retrieval_observatory/tracing/integrations/_duck_typed.py tests/unit/test_adapter_stable_identity.py tests/unit/test_adapter_concurrent_parentage.py tests/unit/test_framework_adapters.py
git commit -m "feat: resolve stable framework operator identity"
```

### Task 6: Rewrite supported framework adapters around the registry

**Files:**
- Modify: `retrieval_observatory/tracing/integrations/langchain.py`
- Modify: `retrieval_observatory/tracing/integrations/llamaindex.py`
- Modify: `retrieval_observatory/tracing/integrations/haystack.py`
- Modify: `retrieval_observatory/tracing/integrations/dspy.py`
- Modify: `retrieval_observatory/tracing/integrations/openai_agents.py`
- Modify: `retrieval_observatory/tracing/integrations/fastapi.py`
- Test: `tests/integration/test_framework_topology_stability.py`
- Modify: `tests/integration/test_langchain_callback.py`
- Modify: `tests/integration/test_llamaindex_callback.py`

**Interfaces:**
- Consumes: sole recorder, `OperatorRegistry`, framework-native event relationships.
- Produces: one adapter implementation per supported framework with stable spans and no compatibility branch.

- [ ] **Step 1: Add repeated and concurrent framework scenarios**

```python
@pytest.mark.parametrize("adapter_fixture", ["langchain", "llamaindex", "haystack", "dspy", "openai_agents"])
def test_framework_topology_is_stable(adapter_fixture, request) -> None:
    fixture = request.getfixturevalue(adapter_fixture)
    first = fixture.run("temporal policy")
    second = fixture.run("ordinary policy")
    assert fixture.operator_signature(first) == fixture.operator_signature(second)
    assert fixture.operator_signature(first)["dense"].parents == ("intent_gate",)
```

Conditional operators may differ in status, but their stable IDs and declared parents must remain present.

- [ ] **Step 2: Run the tests against current adapters**

Run: `pytest tests/integration/test_framework_topology_stability.py tests/integration/test_langchain_callback.py tests/integration/test_llamaindex_callback.py -v`

Expected: failures show random IDs, sequential parentage, or missing skipped operators.

- [ ] **Step 3: Replace adapter-local identity logic**

Each callback constructor must take the sole recorder and registry:

```python
class LangChainRetrievalCallback(BaseCallbackHandler):
    def __init__(self, recorder: TraceRecorder, registry: OperatorRegistry, pipeline_id: str):
        self.recorder = recorder
        self.registry = registry
        self.pipeline_id = pipeline_id
```

Resolve start/end events by framework run ID while emitting manifest-declared stable IDs and parent IDs. Apply the same contract to every supported adapter.

- [ ] **Step 4: Keep FastAPI middleware trace-scoped only**

FastAPI middleware creates/finishes the request trace and manages telemetry lifecycle. Operator wrappers or framework callbacks emit graph spans. Delete any default snippet that calls `.stage()` or invents `bm25`/`dense` stages.

- [ ] **Step 5: Run framework and external graph suites**

Run: `pytest tests/unit/test_framework_adapters.py tests/integration/test_framework_topology_stability.py tests/integration/test_langchain_callback.py tests/integration/test_llamaindex_callback.py tests/integration/test_hybrid_graph_smoke.py -v`

Expected: all pass; two runs produce identical operator identities and valid graph relationships.

- [ ] **Step 6: Commit the adapter cutover**

```bash
git add retrieval_observatory/tracing/integrations tests/unit/test_framework_adapters.py tests/integration/test_framework_topology_stability.py tests/integration/test_langchain_callback.py tests/integration/test_llamaindex_callback.py tests/integration/test_hybrid_graph_smoke.py
git commit -m "refactor: make framework tracing graph-faithful"
```

### Task 7: Make verification prove graph fidelity across representative traces

**Files:**
- Modify: `retrieval_observatory/integrations/verify.py`
- Test: `tests/unit/test_verify_topology_contract.py`
- Test: `tests/integration/test_reference_architecture.py`

**Interfaces:**
- Consumes: `IntegrationManifest`, unified trace query, stable operator signatures.
- Produces: `topology_identity`, `parent_coverage`, `branch_coverage`, `unknown_components`, and `final_output` verification checks.

- [ ] **Step 1: Add failing verification cases**

```python
def test_verification_fails_random_operator_identity(manifest, traces_with_random_ids) -> None:
    report = verify_trace_contract(manifest, traces_with_random_ids)
    assert report.check("topology_identity").status == "error"


def test_verification_requires_every_declared_gate_branch(manifest, temporal_only_traces) -> None:
    report = verify_trace_contract(manifest, temporal_only_traces)
    assert report.check("branch_coverage").status == "error"
    assert report.check("branch_coverage").details["missing"] == ["generic"]
```

- [ ] **Step 2: Confirm current verifier does not detect cross-trace drift**

Run: `pytest tests/unit/test_verify_topology_contract.py -v`

Expected: tests fail because verification checks only within-trace identity and duplicates.

- [ ] **Step 3: Add manifest-to-observation comparison**

```python
def operator_signature(trace: RetrievalTrace) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {span.op_id: (span.op_type, tuple(span.parent_ids)) for span in trace.spans}


def verify_trace_contract(manifest: IntegrationManifest, traces: Sequence[RetrievalTrace]) -> VerificationReport:
    checks = [
        check_declared_operators(manifest, traces),
        check_stable_signatures(manifest, traces),
        check_branch_coverage(manifest, traces),
        check_candidate_parent_groups(manifest, traces),
        check_final_outputs(manifest, traces),
    ]
    return VerificationReport.from_checks(checks)
```

Conditional absence is represented by `SKIPPED_BY_GATE`, so a declared operator must not disappear silently.

- [ ] **Step 4: Run verification and reference architecture tests**

Run: `pytest tests/unit/test_verify_topology_contract.py tests/unit/test_verify_checks.py tests/integration/test_reference_architecture.py -v`

Expected: all pass; `ready` requires stable, sufficiently exercised graph evidence.

- [ ] **Step 5: Commit graph-fidelity verification**

```bash
git add retrieval_observatory/integrations/verify.py tests/unit/test_verify_topology_contract.py tests/unit/test_verify_checks.py tests/integration/test_reference_architecture.py
git commit -m "feat: verify stable observed pipeline topology"
```

## Workstream completion gate

Run:

```bash
pytest tests/unit/test_operator_schema.py tests/unit/test_parent_grouped_candidates.py tests/unit/test_operator_execution_semantics.py tests/unit/test_adapter_stable_identity.py tests/unit/test_adapter_concurrent_parentage.py tests/unit/test_verify_topology_contract.py -v
pytest tests/integration/test_gated_hybrid_dag.py tests/integration/test_framework_topology_stability.py tests/integration/test_reference_architecture.py -v
```

Expected: all tests pass. No supported adapter generates random operator IDs, infers parents from previous-span order, omits declared skipped operators, or collapses parent-grouped candidates.
