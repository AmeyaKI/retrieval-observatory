# Canonical Project Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every competing integration surface with one factual `plan` / `apply` / `verify` service shared by `retobs integrate <project>` and MCP `integrate_project`.

**Architecture:** A typed plan is the immutable handoff between discovery and mutation. Apply validates plan identity and file hashes before an atomic patch set; verify compares representative unified traces with the applied manifest and reports evidence, not file presence.

**Tech Stack:** Python 3.10+, dataclasses, AST, PyYAML, Typer, FastMCP, pytest, pytest-asyncio

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

- `integrations/model.py`: plan, patch, manifest, check, and result contracts.
- `integrations/planner.py`: AST discovery and exact patch construction.
- `integrations/apply.py`: preflight and atomic mutation.
- `integrations/manifest.py`: `retobs/integration.yaml` I/O.
- `integrations/service.py`: sole phase dispatcher.
- `integrations/verify.py`: observed-fidelity verification.
- `cli.py` and `mcp/server.py`: thin, equivalent entrypoints.
- Delete `integrations/wire.py`; reduce `registry.py` to capability metadata.

### Task 1: Define integration contracts

**Files:**
- Create: `retrieval_observatory/integrations/model.py`
- Test: `tests/unit/test_integration_model.py`

**Interfaces:**
- Consumes: none.
- Produces: `IntegrationPhase`, `IntegrationOptions`, `OperatorMapping`, `PatchOperation`, `VerificationScenario`, `IntegrationPlan`, `IntegrationManifest`, `IntegrationCheck`, `IntegrationResult`, all with `to_dict()` / `from_dict()`.

- [ ] **Step 1: Write the failing test**

```python
def test_plan_round_trip_and_apply_validation(tmp_path):
    from retrieval_observatory.integrations.model import IntegrationPlan, PatchOperation
    target = tmp_path / "app.py"
    target.write_text("old", encoding="utf-8")
    plan = IntegrationPlan.create(
        project_root=tmp_path, framework="python", service_id="svc", pipeline_id="pipe",
        patches=[PatchOperation.from_file(tmp_path, target, "new")], operators=[],
        candidate_mapping={"doc_id": "item.id", "score": "item.score", "rank": "enumerate"}, scenarios=[],
    )
    restored = IntegrationPlan.from_dict(plan.to_dict())
    restored.validate_for_apply()
    assert restored.plan_id == plan.plan_id
    assert restored.patches[0].relative_path == "app.py"
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_integration_model.py`

Expected: collection fails with `ModuleNotFoundError: ...integrations.model`.

- [ ] **Step 3: Implement the minimal contract**

```python
class IntegrationPhase(str, Enum):
    PLAN = "plan"
    APPLY = "apply"
    VERIFY = "verify"

@dataclass(frozen=True)
class IntegrationOptions:
    plan: "IntegrationPlan | None" = None
    db_path: str = ".retobs/results.db"

@dataclass(frozen=True)
class PatchOperation:
    relative_path: str
    precondition_sha256: str
    replacement: str

    @classmethod
    def from_file(cls, root: Path, path: Path, replacement: str) -> "PatchOperation":
        return cls(str(path.resolve().relative_to(root.resolve())), sha256(path.read_bytes()).hexdigest(), replacement)

@dataclass(frozen=True)
class OperatorMapping:
    op_id: str
    op_type: str
    symbol: str
    relative_path: str
    parent_ids: tuple[str, ...] = ()
    confidence: float = 1.0

@dataclass(frozen=True)
class VerificationScenario:
    scenario_id: str
    query_text: str
    expected_operator_ids: tuple[str, ...]
    expected_edges: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True)
class IntegrationPlan:
    schema_version: int
    plan_id: str
    project_root: str
    framework: str
    service_id: str
    pipeline_id: str
    patches: tuple[PatchOperation, ...]
    operators: tuple[OperatorMapping, ...]
    candidate_mapping: dict[str, str]
    scenarios: tuple[VerificationScenario, ...]
    unresolved: tuple[str, ...] = ()

    def validate_for_apply(self) -> None:
        if self.unresolved:
            raise ValueError(f"unresolved mappings: {', '.join(self.unresolved)}")
        if not self.candidate_mapping.get("doc_id"):
            raise ValueError("candidate_mapping.doc_id is required")
        low = [op.op_id for op in self.operators if op.confidence < 0.8]
        if low:
            raise ValueError(f"operator confidence below 0.8: {', '.join(low)}")

@dataclass(frozen=True)
class IntegrationManifest:
    schema_version: int
    plan_id: str
    service_id: str
    pipeline_id: str
    operators: tuple[OperatorMapping, ...]
    candidate_mapping: dict[str, str]
    scenarios: tuple[VerificationScenario, ...]

    @classmethod
    def from_plan(cls, plan: IntegrationPlan) -> "IntegrationManifest":
        return cls(1, plan.plan_id, plan.service_id, plan.pipeline_id,
                   plan.operators, plan.candidate_mapping, plan.scenarios)

@dataclass(frozen=True)
class IntegrationCheck:
    check_id: str
    status: Literal["ok", "warn", "error", "unavailable"]
    evidence_class: str
    method_version: str
    sample_size: int
    limitations: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    fix: str | None = None

@dataclass(frozen=True)
class IntegrationResult:
    phase: Literal["plan", "apply", "verify"]
    status: str
    plan: IntegrationPlan | None = None
    changed_files: tuple[str, ...] = ()
    checks: tuple[IntegrationCheck, ...] = ()
    capabilities: dict[str, str] = field(default_factory=dict)
    observed_operator_ids: tuple[str, ...] = ()
    topology_variants: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Implement deterministic `create()`, recursive `to_dict()`, and strict `from_dict()` in the same file; `plan_id` is SHA-256 over canonical JSON excluding `project_root` and truncated to 16 characters.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_integration_model.py`

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/integrations/model.py tests/unit/test_integration_model.py
git commit -m "feat(integration): define canonical contracts"
```

### Task 2: Discover real symbols and construct a reviewable plan

**Files:**
- Modify: `retrieval_observatory/integrations/detect.py:50-151`
- Create: `retrieval_observatory/integrations/planner.py`
- Create: `tests/fixtures/external_fastapi/app.py`
- Test: `tests/unit/test_integration_planner.py`

**Interfaces:**
- Consumes: Task 1 contracts.
- Produces: `build_integration_plan(project_root: Path, framework: str | None = None) -> IntegrationPlan`.

- [ ] **Step 1: Add a failing hybrid-DAG test**

```python
def test_planner_names_real_hybrid_symbols():
    plan = build_integration_plan(Path("tests/fixtures/external_fastapi").resolve())
    by_symbol = {op.symbol: op for op in plan.operators}
    assert by_symbol["bm25_retrieve"].op_type == "SOURCE"
    assert by_symbol["dense_retrieve"].op_type == "SOURCE"
    assert by_symbol["reciprocal_rank_fuse"].op_type == "FUSE"
    assert by_symbol["temporal_filter"].op_type == "FILTER"
    assert by_symbol["cross_encoder_rerank"].op_type == "RERANK"
    assert all("my_retriever" not in patch.replacement for patch in plan.patches)
```

The fixture must define a FastAPI `/retrieve` route calling `route_intent`, `bm25_retrieve`, `dense_retrieve`, `reciprocal_rank_fuse`, `temporal_filter`, and `cross_encoder_rerank` in that order with sparse/dense fan-in.

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_integration_planner.py`

Expected: FAIL because `integrations.planner` is absent.

- [ ] **Step 3: Implement AST discovery**

```python
TYPE_RULES = ((r"gate|intent|route", "GATE"), (r"fuse|fusion|rrf", "FUSE"),
              (r"filter", "FILTER"), (r"rerank|cross_encoder", "RERANK"),
              (r"retrieve|search|bm25|dense", "SOURCE"))

def stable_op_id(relative_path: str, symbol: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", symbol.lower()).strip("_")
    return f"{slug}_{sha256(f'{relative_path}:{symbol}'.encode()).hexdigest()[:8]}"

def build_integration_plan(project_root: Path, framework: str | None = None) -> IntegrationPlan:
    discoveries = discover_python_symbols(project_root)
    operators = [OperatorMapping(
        op_id=stable_op_id(item.relative_path, item.symbol), op_type=item.op_type,
        symbol=item.symbol, relative_path=item.relative_path,
        parent_ids=tuple(stable_op_id(p.relative_path, p.symbol) for p in item.parents),
        confidence=item.confidence,
    ) for item in discoveries.operators]
    return IntegrationPlan.create(
        project_root=project_root, framework=framework or discoveries.framework,
        service_id=project_root.name, pipeline_id=f"{project_root.name}-retrieval",
        patches=build_exact_patches(project_root, discoveries, operators), operators=operators,
        candidate_mapping=discoveries.candidate_mapping,
        scenarios=build_verification_scenarios(discoveries, operators),
    )
```

`build_exact_patches()` must patch detected symbols only and include each target file's SHA-256. Any unknown required document mapping or edge is appended to `IntegrationPlan.unresolved`, never invented.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_integration_planner.py tests/unit/test_integrations_detect.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/integrations/detect.py retrieval_observatory/integrations/planner.py tests/fixtures/external_fastapi/app.py tests/unit/test_integration_planner.py
git commit -m "feat(integration): plan against concrete pipeline symbols"
```

### Task 3: Apply plans atomically and persist intent

**Files:**
- Create: `retrieval_observatory/integrations/apply.py`
- Create: `retrieval_observatory/integrations/manifest.py`
- Test: `tests/unit/test_integration_apply.py`

**Interfaces:**
- Consumes: `IntegrationPlan`.
- Produces: `apply_integration_plan(plan: IntegrationPlan) -> IntegrationResult`; `load_manifest(root: Path) -> IntegrationManifest`.

- [ ] **Step 1: Write failing stale-plan atomicity test**

```python
def test_stale_second_patch_leaves_first_file_unchanged(tmp_path):
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("a", encoding="utf-8"); second.write_text("b", encoding="utf-8")
    plan = make_plan(tmp_path, [PatchOperation.from_file(tmp_path, first, "A"),
                                PatchOperation.from_file(tmp_path, second, "B")])
    second.write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError, match="stale integration plan: b.py"):
        apply_integration_plan(plan)
    assert first.read_text(encoding="utf-8") == "a"
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_integration_apply.py`

Expected: collection fails because `integrations.apply` is absent.

- [ ] **Step 3: Implement preflight and atomic replacement**

```python
def apply_integration_plan(plan: IntegrationPlan) -> IntegrationResult:
    plan.validate_for_apply()
    root = Path(plan.project_root).resolve()
    targets = []
    for patch in plan.patches:
        target = (root / patch.relative_path).resolve()
        if root not in target.parents or sha256(target.read_bytes()).hexdigest() != patch.precondition_sha256:
            raise ValueError(f"stale integration plan: {patch.relative_path}")
        targets.append((target, patch))
    staged = [stage_replacement(target, patch.replacement) for target, patch in targets]
    try:
        for temporary, target in staged:
            os.replace(temporary, target)
        manifest_path = write_manifest(root, IntegrationManifest.from_plan(plan))
    finally:
        for temporary, _ in staged:
            Path(temporary).unlink(missing_ok=True)
    changed = tuple(p.relative_path for p in plan.patches) + (str(manifest_path.relative_to(root)),)
    return IntegrationResult("apply", "applied", plan=plan, changed_files=changed)
```

`write_manifest()` writes `retobs/integration.yaml` with schema, plan ID, service/pipeline identity, operator registry, candidate mapping, privacy/sampling/queue policy, and verification scenarios. Use `NamedTemporaryFile(dir=target.parent, delete=False)` in `stage_replacement()`.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_integration_apply.py`

Expected: stale-plan and successful-manifest tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/integrations/apply.py retrieval_observatory/integrations/manifest.py tests/unit/test_integration_apply.py
git commit -m "feat(integration): apply reviewed plans atomically"
```

### Task 4: Verify observed topology and coverage

**Files:**
- Modify: `retrieval_observatory/integrations/verify.py:42-390`
- Test: `tests/unit/test_integration_verify.py`

**Interfaces:**
- Consumes: `IntegrationManifest`; `BaseStore.list_traces(TraceQuery(service_id=..., pipeline_id=...))` from `02_TRACE_STORAGE_PLAN.md`.
- Produces: `async verify_project(root: Path, store: BaseStore) -> IntegrationResult`.

- [ ] **Step 1: Write failing production-only and identity-drift tests**

```python
@pytest.mark.asyncio
async def test_production_only_trace_can_verify(manifest, memory_store, trace_factory):
    await memory_store.save_trace(trace_factory(run_id=None, op_id="bm25"))
    result = await verify_project_from_manifest(manifest, memory_store)
    assert result.status == "ready"

def test_random_operator_id_fails_stability(manifest, trace_factory):
    result = verify_observed_traces(manifest, [trace_factory(op_id="bm25"), trace_factory(op_id="source_1234")])
    check = next(c for c in result.checks if c.check_id == "stable_operator_identity")
    assert check.status == "error"
    assert check.evidence_class == "measured"
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_integration_verify.py`

Expected: FAIL because verification still requires `list_runs()` and lacks stability checks.

- [ ] **Step 3: Implement evidence-bearing checks**

```python
def verify_observed_traces(manifest, traces):
    declared = {op.op_id: op for op in manifest.operators}
    observed = {span.op_id for trace in traces for span in trace.spans}
    edges = {(parent, span.op_id) for trace in traces for span in trace.spans for parent in span.parent_ids}
    expected_edges = {(parent, op.op_id) for op in manifest.operators for parent in op.parent_ids}
    checks = (
        check("trace_sample", bool(traces), len(traces), "Run every verification scenario."),
        check("expected_operators", set(declared) <= observed, len(traces), f"Missing: {sorted(set(declared)-observed)}"),
        check("stable_operator_identity", observed <= set(declared), len(traces), f"Unknown: {sorted(observed-set(declared))}"),
        check("declared_edges", expected_edges <= edges, len(traces), f"Missing: {sorted(expected_edges-edges)}"),
        check_candidate_transitions(traces), check_timing(traces), check_scenario_coverage(manifest, traces),
    )
    errors = tuple(check.fix or check.check_id for check in checks if check.status == "error")
    return IntegrationResult(
        "verify",
        "ready" if not errors else "failed",
        checks=checks,
        capabilities=capability_matrix(checks),
        observed_operator_ids=tuple(sorted(observed)),
        topology_variants=summarize_topology_variants(traces),
        errors=errors,
    )
```

Every `IntegrationCheck` includes `evidence_class`, `method_version`, `sample_size`, `limitations`, `unavailable_reason`, and `fix`. `capability_matrix()` derives each capability only from its required checks; `summarize_topology_variants()` groups stable node/edge signatures with frequency and scenario IDs. Query traces by service and pipeline; never require a run.

- [ ] **Step 4: Verify pass**

Run: `pytest -q tests/unit/test_integration_verify.py tests/unit/test_verify_checks.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/integrations/verify.py tests/unit/test_integration_verify.py tests/unit/test_verify_checks.py
git commit -m "feat(integration): verify observed graph fidelity"
```

### Task 5: Expose one CLI/MCP service and delete old paths

**Files:**
- Create: `retrieval_observatory/integrations/service.py`
- Modify: `retrieval_observatory/cli.py:533-630`
- Modify: `retrieval_observatory/mcp/server.py:222-248,498-558`
- Delete: `retrieval_observatory/integrations/wire.py`
- Modify: `retrieval_observatory/integrations/registry.py`
- Delete: `tests/unit/test_cli_wire.py`
- Delete: `tests/unit/test_mcp_wire_project.py`
- Delete: `tests/unit/test_integrations_wire.py`
- Test: `tests/unit/test_integration_entrypoints.py`
- Test: `tests/packaging/test_installed_integration.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: `async integrate_project(project_root: Path, phase: IntegrationPhase, options: IntegrationOptions) -> IntegrationResult`.

- [ ] **Step 1: Write failing parity and prohibited-tool tests**

```python
def test_cli_and_service_plan_are_equal(tmp_path):
    direct = asyncio.run(integrate_project(tmp_path, IntegrationPhase.PLAN, IntegrationOptions())).to_dict()
    cli = CliRunner().invoke(app, ["integrate", str(tmp_path), "--phase", "plan"])
    assert cli.exit_code == 0
    assert json.loads(cli.stdout) == direct

def test_mcp_has_only_integrate_project():
    names = {tool.name for tool in build_server()._tool_manager.list_tools()}
    assert "integrate_project" in names
    assert {"wire_project", "bootstrap_project", "plan_integration"}.isdisjoint(names)
```

- [ ] **Step 2: Verify failure**

Run: `pytest -q tests/unit/test_integration_entrypoints.py`

Expected: FAIL because `--phase` and `integrate_project` are absent.

- [ ] **Step 3: Implement the dispatcher and entrypoints**

```python
async def integrate_project(
    project_root: Path,
    phase: IntegrationPhase,
    options: IntegrationOptions,
) -> IntegrationResult:
    root = project_root.resolve()
    if phase is IntegrationPhase.PLAN:
        result = IntegrationResult("plan", "planned", plan=build_integration_plan(root))
    elif phase is IntegrationPhase.APPLY:
        if options.plan is None:
            raise ValueError("apply requires --plan-file or MCP plan payload")
        result = apply_integration_plan(options.plan)
    else:
        result = await verify_project(root, open_store(options.db_path))
    return result
```

The CLI takes `--phase`, `--plan-file`, `--output`, and `--db`; CLI and MCP build `IntegrationOptions` and serialize the returned `IntegrationResult` with `to_dict()`. MCP registers only `_integrate_project` as `integrate_project`. Delete old functions, registrations, files, and tests in this task. Reduce `registry.py` to framework extra/binding metadata without snippets.

- [ ] **Step 4: Run focused, installed-wheel, and prohibited-name gates**

Run: `pytest -q tests/unit/test_integration_entrypoints.py tests/unit/test_mcp_server.py tests/packaging/test_installed_integration.py`

Expected: all tests pass.

Run: `rg -n "wire_project|bootstrap_project|plan_integration|retobs wire" retrieval_observatory tests`

Expected: exit code 1 with no output.

- [ ] **Step 5: Commit**

```bash
git add -A retrieval_observatory/integrations retrieval_observatory/cli.py retrieval_observatory/mcp/server.py tests CHANGELOG.md
git commit -m "refactor(integration): consolidate public integration workflow"
```

## Workstream acceptance gate

Run: `pytest -q tests/unit/test_integration_model.py tests/unit/test_integration_planner.py tests/unit/test_integration_apply.py tests/unit/test_integration_verify.py tests/unit/test_integration_entrypoints.py tests/packaging/test_installed_integration.py`

Expected: all pass. Then run `git diff --check`; expected: no output.
