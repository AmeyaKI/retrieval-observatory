# Documentation, Packaging, and Release Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one coherent, V2-only retobs beta whose source tree, installed wheel, external-project integration, CLI, MCP tools, documentation, dashboard, and published artifact all prove the same public contract.

**Architecture:** Treat the approved public surface as a machine-checked contract rather than prose. Build the wheel once, exercise that exact artifact against four independent external projects and the live dashboard, then promote the same SHA-256-identified files through TestPyPI and PyPI. Remove deprecated and legacy surfaces immediately; no aliases, warning wrappers, compatibility reads, or migration documentation remain.

**Tech Stack:** Python 3.10–3.12, setuptools/build/twine, Typer, MCP Python SDK, pytest, FastAPI, LangChain, LlamaIndex, GitHub Actions, npm/Vitest/Vite, Playwright, Markdown.

## Global Constraints

- The approved design is `retobs_audit_remediation/00_DESIGN.md`; this plan must not weaken its evidence, identity, safety, or clean-break rules.
- The public integration workflow is only `retobs integrate <project> --phase plan|apply|verify` and MCP `integrate_project` with the same phase values and result schemas.
- Workstream 1 owns `IntegrationPhase`, `IntegrationOptions`, `IntegrationPlan`, `IntegrationManifest`, `IntegrationCheck`, `IntegrationResult`, and `integrate_project(project_root, phase, options)`; this workstream consumes those contracts without recreating integration logic.
- Workstream 2 owns the unified `RetrievalTrace`, V2-only store protocol, production-without-run behavior, and reset/one-time-upgrade policy; release fixtures must exercise those contracts through public APIs.
- Workstream 3 owns bounded telemetry, redaction, failure containment, `InstrumentationHealth`, and shutdown behavior; release fixtures must prove application non-interference and health visibility.
- Workstreams 4–7 own stable DAG fidelity, diagnostics, dashboard routes, and analysis contracts; release proof consumes their golden fixtures rather than recomputing their results.
- Delete deprecated and legacy surfaces immediately. Do not add aliases, warning-only wrappers, dual reads, redirects, migration windows, or “removed in v1.0” messages.
- Historical entries in `CHANGELOG.md` remain immutable. Vocabulary checks exclude historical changelog content, `.archive/`, generated output, virtual environments, dependency trees, and Git internals.
- Active public material must not teach `wire`, `bootstrap_project`, `TraceLens`, `Forge`, `Advisor`, `Benchmarks`, V1/V2 user-facing terminology, legacy recorder APIs, or deprecated benchmark aliases.
- The dashboard binds to `127.0.0.1` by default. Every remote bind is explicit.
- A release candidate is the exact wheel and source distribution produced once by the build job. Downstream jobs verify its digest and never rebuild it.
- All user-visible structural changes add one precise line under the appropriate `[Unreleased]` heading in `CHANGELOG.md`.
- New plan documents live under `retobs_audit_remediation/`; `.gitignore` must explicitly allow this directory so the roadmap is reviewable and versioned.

---

## Dependency Contract

This workstream begins after Workstreams 1–3 expose these importable interfaces:

```python
from retrieval_observatory.integrations.model import (
    IntegrationCheck,
    IntegrationManifest,
    IntegrationOptions,
    IntegrationPhase,
    IntegrationPlan,
    IntegrationResult,
)
from retrieval_observatory.integrations.service import (
    integrate_project,
)
from retrieval_observatory.tracing import InstrumentationHealth, RetrievalTrace, TraceRecorder, init
```

The integration service signature is:

```python
async def integrate_project(
    project_root: Path,
    phase: IntegrationPhase,
    options: IntegrationOptions,
) -> IntegrationResult: ...
```

The verification result must expose:

```python
verification.status                  # "ready" | "partially_instrumented" | "not_verified" | "failed"
verification.capabilities            # typed capability matrix
verification.observed_operator_ids   # stable operator IDs across exercised traces
verification.topology_variants       # nodes, edges, frequency, scenario IDs
verification.checks                  # includes topology, candidate, branch, and telemetry-health checks
verification.errors                  # actionable contract failures
```

If these interfaces differ when Workstreams 1–3 land, update this dependency block and every consuming fixture in the same review before implementation begins.

---

### Task 1: Version the Approved Public Surface

**Files:**
- Create: `contracts/public_surface.json`
- Create: `scripts/check_public_surface.py`
- Create: `tests/contracts/__init__.py`
- Create: `tests/contracts/test_public_surface.py`
- Modify: `.gitignore`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Typer application `retrieval_observatory.cli.app`, MCP factory `retrieval_observatory.mcp.server.build_server`, and `retrieval_observatory.__all__`.
- Produces: `contracts/public_surface.json` as the sole allow-list for CLI commands, MCP tools, SDK exports, documentation entry points, package extras, and first-class integration paths.
- Produces: `scripts/check_public_surface.py --json` with exit code `0` only when runtime and manifest match exactly.

- [ ] **Step 1: Add failing contract tests for the approved surface**

Create `tests/contracts/test_public_surface.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import retrieval_observatory as ro
from retrieval_observatory.cli import app
from retrieval_observatory.mcp.server import build_server


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
REMOVED = {
    "advisor",
    "benchmark_config",
    "benchmark_config_file",
    "benchmark_pipeline_descriptor",
    "benchmark_vs_baseline",
    "bootstrap_project",
    "forge",
    "get_pareto_frontier",
    "get_pipeline_diagram",
    "get_recommendations",
    "plan_integration",
    "quickstart",
    "run",
    "tracelens",
    "wire",
    "wire_project",
}


def _mcp_tool_names() -> set[str]:
    server = build_server()
    return {tool.name for tool in server._tool_manager.list_tools()}


def test_cli_help_matches_contract_exactly() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout
    commands = {command.name for command in app.registered_commands if command.name}
    commands.update(group.name for group in app.registered_groups if group.name and not group.hidden)
    assert commands == set(CONTRACT["cli_commands"])
    assert REMOVED.isdisjoint(commands)


@pytest.mark.parametrize("command", sorted(REMOVED & {"advisor", "forge", "quickstart", "run", "tracelens", "wire"}))
def test_removed_cli_commands_are_unknown(command: str) -> None:
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.stdout
    assert "deprecated" not in result.stdout.lower()


def test_mcp_tools_match_contract_exactly() -> None:
    names = _mcp_tool_names()
    assert names == set(CONTRACT["mcp_tools"])
    assert REMOVED.isdisjoint(names)


def test_sdk_exports_match_contract_exactly() -> None:
    assert set(ro.__all__) == set(CONTRACT["sdk_exports"])
    assert REMOVED.isdisjoint(ro.__all__)
```

- [ ] **Step 2: Add the approved machine-readable manifest**

Create `contracts/public_surface.json`:

```json
{
  "schema_version": 1,
  "cli_commands": [
    "compare",
    "demo",
    "evaluate",
    "inspect-query",
    "integrate",
    "production",
    "report",
    "serve",
    "testsets",
    "verify"
  ],
  "mcp_tools": [
    "compare",
    "describe_config",
    "evaluate",
    "evaluate_file",
    "get_pipeline_graph",
    "get_report",
    "inspect_query",
    "integrate_project",
    "push_traces",
    "validate_config",
    "verify_integration"
  ],
  "sdk_exports": [
    "Comparison",
    "Document",
    "IntegrationOptions",
    "Query",
    "QueryEvidence",
    "RetrievalTrace",
    "Run",
    "TestSet",
    "TraceRecorder",
    "compare",
    "evaluate",
    "generate_testset",
    "init",
    "inspect_query"
  ],
  "documentation": [
    "README.md",
    "docs/START.md",
    "docs/WORKFLOW.md",
    "docs/CONCEPTS.md",
    "docs/REFERENCE.md",
    "docs/INTEGRATIONS.md",
    "docs/integrations/AGENT_QUICKSTART.md",
    "docs/integrations/mcp.md",
    "docs/integrations/api.md",
    "docs/PRIVACY.md",
    "docs/RELEASE_CHECKLIST.md"
  ],
  "first_class_integrations": ["python", "http", "fastapi", "langchain", "llamaindex"],
  "supported_example_integrations": ["dspy", "haystack", "openai-agents"],
  "optional_extras": [
    "beir",
    "classifier",
    "cohere",
    "dashboard",
    "demo",
    "dense",
    "dev",
    "dspy",
    "haystack",
    "hf",
    "langchain",
    "llamaindex",
    "llm-judge",
    "mcp",
    "openai-agents",
    "pgvector",
    "postgres",
    "qdrant"
  ]
}
```

- [ ] **Step 3: Implement the reusable surface checker**

Create `scripts/check_public_surface.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import retrieval_observatory as ro
from retrieval_observatory.cli import app
from retrieval_observatory.mcp.server import build_server


ROOT = Path(__file__).resolve().parents[1]


def actual_surface() -> dict[str, list[str]]:
    cli = {command.name for command in app.registered_commands if command.name}
    cli.update(group.name for group in app.registered_groups if group.name and not group.hidden)
    mcp = {tool.name for tool in build_server()._tool_manager.list_tools()}
    return {
        "cli_commands": sorted(cli),
        "mcp_tools": sorted(mcp),
        "sdk_exports": sorted(ro.__all__),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    expected = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
    actual = actual_surface()
    mismatches = {
        key: {"expected": sorted(expected[key]), "actual": actual[key]}
        for key in actual
        if sorted(expected[key]) != actual[key]
    }
    if args.json:
        print(json.dumps({"valid": not mismatches, "mismatches": mismatches}, indent=2, sort_keys=True))
    elif mismatches:
        for key, values in mismatches.items():
            print(f"{key}: expected {values['expected']}; actual {values['actual']}", file=sys.stderr)
    else:
        print("Public surface matches contracts/public_surface.json.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Make remediation plans trackable**

Add immediately after the `*.md` rule in `.gitignore`:

```gitignore
!retobs_audit_remediation/
!retobs_audit_remediation/**/*.md
```

- [ ] **Step 5: Run the tests and confirm they fail against the current mixed surface**

Run:

```bash
pytest tests/contracts/test_public_surface.py -v
```

Expected: failures list existing aliases such as `run`, `wire_project`, or `benchmark_config`; the failure demonstrates that the contract detects the current drift.

- [ ] **Step 6: Record the new release contract**

Under `CHANGELOG.md` → `[Unreleased]` → `Added`, add:

```markdown
- `contracts/public_surface.json` and `scripts/check_public_surface.py` — make the supported CLI, MCP, SDK, documentation, extras, and integration tiers release-gated contracts.
```

- [ ] **Step 7: Commit the contract before deleting implementations**

```bash
git add .gitignore CHANGELOG.md contracts/public_surface.json scripts/check_public_surface.py tests/contracts retobs_audit_remediation
git commit -m "test: define the supported public surface"
```

---

### Task 2: Delete Deprecated and Legacy Public Surfaces

**Files:**
- Modify: `retrieval_observatory/cli.py`
- Modify: `retrieval_observatory/mcp/server.py`
- Modify: `retrieval_observatory/__init__.py`
- Modify: `retrieval_observatory/tracing/__init__.py`
- Delete: `docs/MIGRATION.md`
- Delete: `tests/unit/test_cli_wire.py`
- Delete: `tests/unit/test_mcp_wire_project.py`
- Modify: `tests/unit/test_mcp_integration_tools.py`
- Modify: `tests/unit/test_mcp_server.py`
- Modify: `tests/unit/test_packaging.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Workstream 1 `integrate_project`; Workstream 2 unified `RetrievalTrace`; Workstream 3 sole `TraceRecorder`, `InstrumentationHealth`, and `init`.
- Produces: exact conformance to `contracts/public_surface.json` with no compatibility aliases.
- Preserves: internal implementation packages only when they remain private and do not leak into user-visible names, schemas, routes, or examples.

- [ ] **Step 1: Replace alias-oriented tests with absence and parity tests**

In `tests/unit/test_mcp_integration_tools.py`, replace tests for `_bootstrap_project`, `_wire_project`, and `plan_integration` with:

```python
@pytest.mark.asyncio
async def test_integrate_project_tool_uses_canonical_service(tmp_path, monkeypatch):
    calls = []

    async def fake_integrate(project_root, *, phase, options=None, plan_path=None):
        calls.append((project_root, phase, plan_path))
        return SimpleNamespace(model_dump=lambda mode="json": {"phase": phase, "status": "planned"})

    monkeypatch.setattr("retrieval_observatory.integrations.service.integrate_project", fake_integrate)
    result = await server._integrate_project(str(tmp_path), phase="plan")
    assert result == {"phase": "plan", "status": "planned"}
    assert calls == [(str(tmp_path), "plan", None)]


def test_removed_mcp_functions_do_not_exist():
    for name in (
        "_bootstrap_project",
        "_wire_project",
        "_plan_integration",
        "_benchmark_pipeline_descriptor",
    ):
        assert not hasattr(server, name)
```

In `tests/unit/test_mcp_server.py`, assert the complete MCP tool set equals the manifest rather than checking selected names.

- [ ] **Step 2: Delete CLI aliases and warning wrappers**

Remove these registrations and their alias-only callbacks from `retrieval_observatory/cli.py`:

```text
app.add_typer(forge_app, ...)
app.add_typer(tracelens_app, ...)
app.add_typer(advisor_app, ...)
@app.command(hidden=True, deprecated=True) def run(...)
@app.command("wire", hidden=True, deprecated=True) def wire_cmd(...)
@app.command(hidden=True, deprecated=True) def inspect(...)
@app.command(hidden=True, deprecated=True) def quickstart(...)
```

Remove duplicate decorators that bind `testsets` functions to `forge_app` and `production` functions to `tracelens_app`. Make `doctor` either a supported command in `contracts/public_surface.json` with a nondeprecated contract or remove it; this plan chooses removal because installation health is covered by `verify`, release smoke, and explicit error messages.

- [ ] **Step 3: Collapse MCP registration to the approved tool set**

In `retrieval_observatory/mcp/server.py`, remove legacy descriptor normalization and these tool registrations:

```text
plan_integration
wire_project
bootstrap_project
benchmark_config
benchmark_config_file
benchmark_pipeline_descriptor
benchmark_vs_baseline
get_pareto_frontier
get_recommendations
get_pipeline_diagram
```

Register the Workstream 1 wrapper:

```python
async def _integrate_project(
    project_root: str,
    phase: str,
    plan_path: str | None = None,
) -> dict[str, object]:
    from retrieval_observatory.integrations.model import IntegrationOptions
    from retrieval_observatory.integrations.service import integrate_project

    result = await integrate_project(
        project_root,
        phase=phase,
        options=IntegrationOptions(),
        plan_path=plan_path,
    )
    return result.model_dump(mode="json")
```

Register only the names in `contracts/public_surface.json`.

- [ ] **Step 4: Remove legacy SDK exports**

Replace the import and `__all__` lists in `retrieval_observatory/__init__.py` with the exact canonical types/functions named by `contracts/public_surface.json`. Remove `benchmark`, `run_from_config`, `BenchmarkReport`, `FunctionRetriever`, `FunctionReranker`, `retriever`, `reranker`, `as_retriever`, `fuse`, and `StageSnapshot` from the public namespace. Do not delete still-needed internal implementation in this task; absence from the public contract is the release requirement.

- [ ] **Step 5: Remove legacy recorder exports and documentation**

In `retrieval_observatory/tracing/__init__.py`, export only `RetrievalTrace`, the sole `TraceRecorder`, supported sinks, `InstrumentationHealth`, `init`, and the Workstream 4 framework adapters. Delete `docs/MIGRATION.md`; it exists only to teach the compatibility window that the approved design rejects.

- [ ] **Step 6: Run focused tests**

```bash
pytest tests/contracts/test_public_surface.py tests/unit/test_mcp_integration_tools.py tests/unit/test_mcp_server.py tests/unit/test_packaging.py -v
```

Expected: all tests pass; removed CLI commands produce “No such command”; removed MCP tools and SDK aliases are absent.

- [ ] **Step 7: Record each logical removal**

Under `CHANGELOG.md` → `[Unreleased]` → `Removed`, add:

```markdown
- `retrieval_observatory/cli.py` — remove deprecated `run`, `wire`, `doctor`, `inspect`, `quickstart`, `forge`, `tracelens`, and `advisor` command surfaces.
- `retrieval_observatory/mcp/server.py` — remove wiring, bootstrap, benchmark-descriptor, Pareto, recommendation, and diagram aliases in favor of the task-oriented MCP contract.
- `retrieval_observatory/__init__.py` and `retrieval_observatory/tracing/__init__.py` — remove legacy benchmark, snapshot, recorder, and helper exports from the supported SDK.
- `docs/MIGRATION.md` — remove the compatibility-window guide after the beta clean break.
```

- [ ] **Step 8: Commit the clean public surface**

```bash
git add CHANGELOG.md retrieval_observatory tests docs/MIGRATION.md
git commit -m "refactor: remove deprecated public surfaces"
```

---

### Task 3: Gate Active Vocabulary and Documentation Paths

**Files:**
- Create: `contracts/forbidden_vocabulary.json`
- Create: `scripts/check_public_vocabulary.py`
- Create: `tests/contracts/test_public_vocabulary.py`
- Modify: `scripts/check_markdown_links.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: public documentation list in `contracts/public_surface.json`.
- Produces: a deterministic scan that rejects deprecated terms and active references while excluding immutable history and private archives.
- Produces: expanded Markdown link validation for README, governance files, public docs, and public examples.

- [ ] **Step 1: Define forbidden active vocabulary precisely**

Create `contracts/forbidden_vocabulary.json`:

```json
{
  "schema_version": 1,
  "patterns": {
    "\\bwire_project\\b": "use integrate_project",
    "\\bbootstrap_project\\b": "use integrate_project",
    "\\bplan_integration\\b": "use integrate_project phase plan",
    "\\bretobs wire\\b": "use retobs integrate",
    "\\bretobs quickstart\\b": "use retobs integrate or retobs demo",
    "\\b(?:TraceRecorderV2|LegacyTraceRecorder)\\b": "use the sole TraceRecorder",
    "\\bTraceLens\\b": "use Production",
    "\\bForge\\b": "use Test Sets",
    "\\bAdvisor\\b": "use findings or compare",
    "\\bBenchmarks\\b": "use Runs or evaluations",
    "deprecated=True": "delete the deprecated registration",
    "removed in v1\\.0": "delete the compatibility message",
    "legacy (alias|surface|reader|route|recorder|trace)": "delete the compatibility implementation"
  },
  "scan_roots": [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs",
    "examples",
    "retrieval_observatory",
    "tests"
  ],
  "exclude": [
    ".archive",
    ".git",
    ".pytest_cache",
    ".venv",
    "CHANGELOG.md",
    "docs/PRODUCT_AUDIT_AND_REDESIGN.md",
    "docs/verification",
    "node_modules",
    "retobs_audit_remediation"
  ]
}
```

- [ ] **Step 2: Implement the scanner with file and line evidence**

Create `scripts/check_public_vocabulary.py`:

```python
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "contracts/forbidden_vocabulary.json").read_text(encoding="utf-8"))
TEXT_SUFFIXES = {".html", ".json", ".md", ".py", ".toml", ".tsx", ".ts", ".yaml", ".yml"}


def excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(rel == item or rel.startswith(f"{item}/") for item in CONFIG["exclude"])


def main() -> int:
    failures: list[str] = []
    patterns = [(re.compile(raw, re.IGNORECASE), replacement) for raw, replacement in CONFIG["patterns"].items()]
    for root_name in CONFIG["scan_roots"]:
        root = ROOT / root_name
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or excluded(path) or path.suffix not in TEXT_SUFFIXES:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for pattern, replacement in patterns:
                    if pattern.search(line):
                        failures.append(
                            f"{path.relative_to(ROOT)}:{line_number}: {pattern.pattern!r}; {replacement}"
                        )
    if failures:
        print("Forbidden active vocabulary:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Active public vocabulary contains no removed terms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Add a scanner contract test**

Create `tests/contracts/test_public_vocabulary.py`:

```python
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_active_tree_has_no_removed_vocabulary() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_public_vocabulary.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 4: Expand Markdown link coverage**

In `scripts/check_markdown_links.py`, make `markdown_files()` include:

```python
roots = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SECURITY.md",
    ROOT / "CODE_OF_CONDUCT.md",
]
roots.extend((ROOT / "docs").rglob("*.md"))
roots.extend((ROOT / "examples").rglob("*.md"))
```

Retain exclusions for private audits and archives. Extend local link validation so an anchor such as `docs/START.md#first-evaluation` must match a normalized Markdown heading in the target file.

- [ ] **Step 5: Add both checks to PR CI before tests**

In `.github/workflows/ci.yml`, add after installation:

```yaml
      - name: Public surface contract
        run: python scripts/check_public_surface.py

      - name: Removed vocabulary
        run: python scripts/check_public_vocabulary.py

      - name: Markdown links and anchors
        run: python scripts/check_markdown_links.py
```

- [ ] **Step 6: Run the scans and remove every reported active reference**

```bash
python scripts/check_public_surface.py
python scripts/check_public_vocabulary.py
python scripts/check_markdown_links.py
```

Expected: each prints a single success line and exits `0`. Do not suppress a finding by widening exclusions unless the file is immutable history or private plan evidence already listed in the contract.

- [ ] **Step 7: Commit the vocabulary gate**

```bash
git add CHANGELOG.md contracts scripts tests/contracts .github/workflows/ci.yml
git commit -m "ci: reject removed public vocabulary"
```

---

### Task 4: Add Four Independent External Integration Fixtures

**Files:**
- Create: `tests/external_projects/python_callable/pyproject.toml`
- Create: `tests/external_projects/python_callable/app/retriever.py`
- Create: `tests/external_projects/python_callable/data/{corpus,queries,qrels}.jsonl`
- Create: `tests/external_projects/python_callable/expected.json`
- Create: `tests/external_projects/fastapi_hybrid_dag/pyproject.toml`
- Create: `tests/external_projects/fastapi_hybrid_dag/app/main.py`
- Create: `tests/external_projects/fastapi_hybrid_dag/data/{corpus,queries,qrels}.jsonl`
- Create: `tests/external_projects/fastapi_hybrid_dag/expected.json`
- Create: `tests/external_projects/langchain_retriever/pyproject.toml`
- Create: `tests/external_projects/langchain_retriever/app/pipeline.py`
- Create: `tests/external_projects/langchain_retriever/data/{corpus,queries,qrels}.jsonl`
- Create: `tests/external_projects/langchain_retriever/expected.json`
- Create: `tests/external_projects/llamaindex_retriever/pyproject.toml`
- Create: `tests/external_projects/llamaindex_retriever/app/pipeline.py`
- Create: `tests/external_projects/llamaindex_retriever/data/{corpus,queries,qrels}.jsonl`
- Create: `tests/external_projects/llamaindex_retriever/expected.json`
- Create: `tests/external_projects/conftest.py`
- Create: `tests/external_projects/test_fixture_contracts.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Workstream 1 plan/apply/verify and integration manifest; Workstream 2 trace/store service queries; Workstream 3 telemetry health.
- Produces: repositories that run without importing the source checkout and encode expected operator IDs, graph edges, route variants, final candidates, unchanged application outputs, and required capabilities.
- Constraint: fixture application code contains no retobs imports before `apply`; the apply phase creates only the reviewed instrumentation patch and `retobs/integration.yaml`.

- [ ] **Step 1: Define one shared fixture contract**

Create each `expected.json` with this shape; use the exact values below for the FastAPI fixture:

```json
{
  "service_id": "external-hybrid-api",
  "pipeline_id": "hybrid-search-v1",
  "required_operator_ids": [
    "intent_gate",
    "bm25",
    "dense",
    "rrf_fusion",
    "temporal_filter",
    "rerank"
  ],
  "required_edges": [
    ["intent_gate", "bm25"],
    ["intent_gate", "dense"],
    ["bm25", "rrf_fusion"],
    ["dense", "rrf_fusion"],
    ["rrf_fusion", "temporal_filter"],
    ["temporal_filter", "rerank"]
  ],
  "scenario_ids": ["hybrid", "lexical_only", "gate_skip", "retriever_error"],
  "expected_final_doc_ids": {
    "hybrid": ["d-current", "d-hybrid"],
    "lexical_only": ["d-lexical"],
    "gate_skip": [],
    "retriever_error": []
  },
  "required_capabilities": [
    "candidate_transitions",
    "operator_debugging",
    "production_investigation",
    "stable_topology"
  ]
}
```

The callable fixture uses `source` only. LangChain uses `langchain_retriever`; LlamaIndex uses `llamaindex_retriever`. Each expected ID is deterministic and repeated across at least two queries.

- [ ] **Step 2: Implement the complex FastAPI host application without retobs dependencies**

Create `tests/external_projects/fastapi_hybrid_dag/app/main.py` with named functions `intent_gate`, `bm25`, `dense`, `rrf_fusion`, `temporal_filter`, and `rerank`. The `/retrieve` POST route returns:

```json
{
  "query_id": "q-hybrid",
  "route": "hybrid",
  "documents": [
    {"id": "d-current", "score": 0.97, "rank": 1},
    {"id": "d-hybrid", "score": 0.88, "rank": 2}
  ]
}
```

for the hybrid scenario before and after instrumentation. The error scenario returns the same application-defined `503` and JSON error body with telemetry enabled and disabled.

- [ ] **Step 3: Implement plain Python, LangChain, and LlamaIndex hosts**

Each fixture must:

```text
1. expose one obvious retrieval entrypoint;
2. return candidates with stable document IDs, rank, score, and non-JSON-native metadata;
3. execute two queries so operator identity stability is testable;
4. provide a command that writes application output to stdout as canonical JSON;
5. contain its own pyproject.toml and framework dependency;
6. avoid relative imports from the retobs repository.
```

Use frozen minimum/maximum framework versions in fixture CI matrices rather than unconstrained latest installs.

- [ ] **Step 4: Add fixture-shape tests before invoking integration**

Create `tests/external_projects/test_fixture_contracts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parent
FIXTURES = ["python_callable", "fastapi_hybrid_dag", "langchain_retriever", "llamaindex_retriever"]


@pytest.mark.parametrize("name", FIXTURES)
def test_external_fixture_is_self_contained(name: str) -> None:
    root = ROOT / name
    expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    assert (root / "pyproject.toml").is_file()
    assert expected["required_operator_ids"]
    assert expected["scenario_ids"]
    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "app").rglob("*.py"))
    assert "retrieval_observatory" not in source
    assert "sys.path" not in source
```

- [ ] **Step 5: Run fixture contract tests**

```bash
pytest tests/external_projects/test_fixture_contracts.py -v
```

Expected: 4 passed; each host is self-contained and uninstrumented before apply.

- [ ] **Step 6: Commit the external repositories**

```bash
git add CHANGELOG.md tests/external_projects
git commit -m "test: add external integration repositories"
```

---

### Task 5: Exercise Plan, Apply, Verify, Fidelity, and Non-Interference from a Wheel

**Files:**
- Create: `scripts/smoke_external_project.py`
- Create: `tests/release/test_external_wheel.py`
- Create: `tests/release/test_wheel_isolation.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `dist/retrieval_observatory-*.whl`, four external fixtures, Workstreams 1–4 public APIs.
- Produces: `artifacts/external-fixtures/<fixture>/verification.json`, `plan.json`, `apply.json`, `before.json`, `after.json`, and `telemetry-health.json`.
- Guarantees: subprocesses run outside the checkout with `PYTHONPATH` removed and import `retrieval_observatory` from the supplied virtual environment only.

- [ ] **Step 1: Write wheel-isolation tests**

Create `tests/release/test_wheel_isolation.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_release_python_imports_installed_distribution(tmp_path: Path, release_python: Path) -> None:
    result = subprocess.run(
        [release_python, "-c", "import json,retrieval_observatory as r; print(json.dumps({'file': r.__file__}))"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": str(release_python.parent)},
    )
    imported = Path(json.loads(result.stdout)["file"]).resolve()
    assert "site-packages" in imported.parts
    assert "retrieval-observatory" not in str(imported.parent.parent)
```

- [ ] **Step 2: Implement the external harness CLI**

`scripts/smoke_external_project.py` accepts:

```text
--wheel PATH                 exact wheel under test
--fixture NAME|all          fixture selector
--artifacts PATH            output root
--keep-workdir              retain temp copies only when debugging
```

For each fixture it must perform these subprocess operations:

```bash
python -m venv <temp>/venv
<temp>/venv/bin/pip install --index-url https://pypi.org/simple <wheel>[dashboard,mcp,<framework-extra>]
<fixture-command> > <artifacts>/before.json
<temp>/venv/bin/retobs integrate <copied-fixture> --phase plan --output <artifacts>/plan.json
<temp>/venv/bin/retobs integrate <copied-fixture> --phase apply --plan <artifacts>/plan.json --output <artifacts>/apply.json
<fixture-command> > <artifacts>/after.json
<temp>/venv/bin/retobs integrate <copied-fixture> --phase verify --plan <artifacts>/plan.json --output <artifacts>/verification.json
```

The script exits nonzero unless:

```python
before == after
set(expected["required_operator_ids"]) <= set(verification["observed_operator_ids"])
set(map(tuple, expected["required_edges"])) <= observed_edges
verification["status"] == "ready"
all(verification["capabilities"][name]["available"] for name in expected["required_capabilities"])
verification["telemetry_health"]["serialization_failures"] == 0
verification["telemetry_health"]["export_failures"] == 0
```

- [ ] **Step 3: Prove production traces do not require an evaluation Run**

For the FastAPI fixture, call the instrumented endpoint before any `retobs evaluate`. Assert through the installed package's public API:

```python
services = client.production.list_services()
assert "external-hybrid-api" in {service.service_id for service in services}
traces = client.production.list_traces(service_id="external-hybrid-api")
assert traces
assert all(trace.run_id is None for trace in traces)
```

Persist the response in `artifacts/external-fixtures/fastapi_hybrid_dag/production.json`.

- [ ] **Step 4: Prove telemetry failure cannot change host behavior**

Run the FastAPI fixture with an injected exporter that raises on every batch. Send the hybrid, gate-skip, and retriever-error requests. Assert status code and JSON body equal the telemetry-disabled golden files, while:

```python
assert health.export_failures >= 1
assert health.exported_traces == 0
assert health.queue_depth <= health.queue_capacity
```

- [ ] **Step 5: Add a release test wrapper**

Create `tests/release/test_external_wheel.py` that invokes the script against a wheel path supplied by `RETOBS_RELEASE_WHEEL` and skips only when that environment variable is absent from ordinary source-test runs. In release CI, absence of `RETOBS_RELEASE_WHEEL` is a workflow configuration error because the job sets it explicitly.

- [ ] **Step 6: Run one focused fixture during development**

```bash
python -m build
python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture fastapi_hybrid_dag --artifacts artifacts/external-fixtures
```

Expected: `fastapi_hybrid_dag: PASS`; before/after JSON is byte-equivalent after canonical formatting; verification is `ready`; the unified production trace is visible without a Run.

- [ ] **Step 7: Run all fixtures**

```bash
python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture all --artifacts artifacts/external-fixtures
```

Expected: four `PASS` lines and exit `0`.

- [ ] **Step 8: Commit the wheel-only harness**

```bash
git add CHANGELOG.md pyproject.toml scripts/smoke_external_project.py tests/release
git commit -m "test: verify external integrations from the wheel"
```

---

### Task 6: Expand the Installed-Wheel Golden Smoke

**Files:**
- Modify: `scripts/smoke_wheel.py`
- Modify: `tests/unit/test_packaging.py`
- Create: `tests/release/test_wheel_contents.py`
- Modify: `.github/workflows/publish.yml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: exact release wheel and `contracts/public_surface.json`.
- Produces: `artifacts/wheel-smoke.json` containing distribution version, import path, public-surface result, callable Run ID, production trace ID, loopback host, and bundled asset checks.
- Guarantees: smoke executes with current working directory outside the source tree.

- [ ] **Step 1: Add wheel content assertions**

Create `tests/release/test_wheel_contents.py`:

```python
from __future__ import annotations

import zipfile
from pathlib import Path


def test_release_wheel_contains_required_runtime_assets(release_wheel: Path) -> None:
    with zipfile.ZipFile(release_wheel) as archive:
        names = set(archive.namelist())
    required_suffixes = {
        "retrieval_observatory/dashboard/ui/dist/index.html",
        "retrieval_observatory/examples/evaluate_scifact.yaml",
    }
    assert required_suffixes <= names
    assert not any("quickstart" in name.lower() for name in names)
    assert not any("migration" in name.lower() for name in names)
```

- [ ] **Step 2: Replace the callable-only smoke with the release golden path**

Refactor `scripts/smoke_wheel.py` into `main()` and add arguments `--output` and `--expected-version`. It must:

```text
1. verify import path contains site-packages;
2. compare importlib.metadata.version("retrieval-observatory") with --expected-version;
3. call scripts/check_public_surface.py using the installed console environment;
4. execute a callable evaluation with qrels and inspect one query;
5. initialize the default `TraceRecorder` and record one production trace without `run_id`;
6. list the production service and retrieve that trace;
7. assert telemetry health reports one accepted/exported trace and no failures;
8. inspect Typer/MCP inventories against the bundled public contract;
9. start `retobs serve --port 0` and assert the reported bind host is 127.0.0.1;
10. verify bundled UI index and canonical example exist;
11. write canonical JSON evidence to --output.
```

- [ ] **Step 3: Rename bundled examples to active vocabulary**

Rename:

```text
retrieval_observatory/examples/quickstart_scifact.yaml -> retrieval_observatory/examples/evaluate_scifact.yaml
examples/basic/sdk_quickstart.py -> examples/basic/evaluate_callable.py
examples/basic/quickstart.py -> examples/basic/evaluate_toy.py
examples/basic/quickstart_scifact.yaml -> examples/basic/evaluate_scifact.yaml
examples/integrations/http_quickstart/ -> examples/integrations/http_evaluation/
examples/integrations/mcp_agent_quickstart.yaml -> examples/integrations/mcp_agent.yaml
```

Update `tests/unit/test_packaging.py`, package-data checks, docs, workflows, and imports to the new paths in the same commit.

- [ ] **Step 4: Run the clean installed-wheel smoke locally**

```bash
python -m build
python -m venv /tmp/retobs-release-smoke
/tmp/retobs-release-smoke/bin/pip install --index-url https://pypi.org/simple "$(pwd)"/dist/retrieval_observatory-*.whl[dashboard,mcp]
cd /tmp
/tmp/retobs-release-smoke/bin/python /Users/ameyakiwalkar/Documents/retrieval-observatory/scripts/smoke_wheel.py --expected-version 0.5.0 --output /tmp/wheel-smoke.json
```

Expected: `Wheel release smoke passed`; `/tmp/wheel-smoke.json` records a site-packages import, one Run, one production trace, matching public surfaces, and `127.0.0.1`.

- [ ] **Step 5: Commit installed-package proof**

```bash
git add CHANGELOG.md examples retrieval_observatory/examples scripts/smoke_wheel.py tests/unit/test_packaging.py tests/release .github/workflows/publish.yml
git commit -m "test: expand installed wheel release proof"
```

---

### Task 7: Build Once and Run the Full CI Matrix Against the Artifact

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/release-candidate.yml`
- Modify: `.github/workflows/retrieval-ci.yml`
- Modify: `Makefile`
- Modify: `CONTRIBUTING.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: source tests, UI lockfile, release wheel, external fixture harness, Workstream 5–7 golden dashboard data.
- Produces: one `release-dist` artifact and one `release-evidence` artifact; every artifact includes SHA-256 checksums and machine-readable results.
- Separates: fast source checks on every PR from wheel-only release-candidate checks, while keeping both required before publication.

- [ ] **Step 1: Keep PR source gates deterministic**

Make `.github/workflows/ci.yml` run:

```yaml
      - run: pip install -e ".[dev,dashboard,demo,dense,mcp]"
      - run: npm ci --prefix retrieval_observatory/dashboard/ui
      - run: ruff check retrieval_observatory tests scripts
      - run: python scripts/check_public_surface.py
      - run: python scripts/check_public_vocabulary.py
      - run: python scripts/check_markdown_links.py
      - run: pytest tests/unit tests/contracts -v --tb=short
      - run: pytest tests/integration -v --tb=short -m "not slow"
      - run: npm run test --prefix retrieval_observatory/dashboard/ui -- --run
      - run: npm run build --prefix retrieval_observatory/dashboard/ui
```

Retain PostgreSQL and browser jobs. Remove editable-install framework smoke jobs from this workflow after their stronger wheel-only replacements exist.

- [ ] **Step 2: Add the release-candidate build job**

Create `.github/workflows/release-candidate.yml` triggered by `workflow_call` and `workflow_dispatch`. Its `build` job must:

```yaml
      - run: npm ci --prefix retrieval_observatory/dashboard/ui
      - run: npm run build --prefix retrieval_observatory/dashboard/ui
      - run: python -m pip install build twine
      - run: python -m build
      - run: twine check dist/*
      - run: shasum -a 256 dist/* > dist/SHA256SUMS
      - uses: actions/upload-artifact@v4
        with:
          name: release-dist
          path: dist/
          if-no-files-found: error
```

- [ ] **Step 3: Add wheel-only Python and framework jobs**

Download `release-dist`, verify `shasum -a 256 -c dist/SHA256SUMS`, then run matrices:

```yaml
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12"]
```

and:

```yaml
strategy:
  matrix:
    fixture: [python_callable, fastapi_hybrid_dag, langchain_retriever, llamaindex_retriever]
```

Each matrix job installs `dist/*.whl`, never `pip install -e`, and uploads its evidence JSON.

- [ ] **Step 4: Run store, UI, and browser release gates**

Add jobs for:

```text
SQLite contract suite
PostgreSQL contract suite against postgres:16
Vitest and Vite bundle budgets
wheel-installed dashboard server
Playwright desktop and 390px mobile workflow
no uncaught browser console errors
no API response with status >= 500
```

The dashboard job seeds deterministic release data through the installed wheel, not source imports.

- [ ] **Step 5: Preserve reviewable retrieval comparison artifacts**

Update `.github/workflows/retrieval-ci.yml` to install the wheel produced by `release-candidate.yml`, generate Markdown/HTML comparison artifacts, append Markdown to `$GITHUB_STEP_SUMMARY`, and record the wheel digest in both reports.

- [ ] **Step 6: Add parity commands to Makefile**

Add:

```make
.PHONY: contracts release-build release-smoke release-external

contracts:
	python scripts/check_public_surface.py
	python scripts/check_public_vocabulary.py
	python scripts/check_markdown_links.py
	pytest tests/contracts -q

release-build: dashboard-build
	python -m build
	twine check dist/*

release-smoke: release-build
	python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture all --artifacts artifacts/external-fixtures

release-external:
	python scripts/smoke_external_project.py --wheel $(WHEEL) --fixture all --artifacts artifacts/external-fixtures
```

- [ ] **Step 7: Verify workflow YAML and local parity**

```bash
make contracts
make release-smoke
npm run test --prefix retrieval_observatory/dashboard/ui -- --run
npm run build --prefix retrieval_observatory/dashboard/ui
```

Expected: all commands exit `0`; four external fixtures pass against the built wheel.

- [ ] **Step 8: Commit CI artifact testing**

```bash
git add CHANGELOG.md CONTRIBUTING.md Makefile .github/workflows
git commit -m "ci: test the built wheel across release gates"
```

---

### Task 8: Promote One Digest Through TestPyPI and PyPI

**Files:**
- Modify: `.github/workflows/publish.yml`
- Create: `scripts/verify_release_artifact.py`
- Create: `tests/contracts/test_publish_workflow.py`
- Modify: `docs/informative/PYPI_PUBLISH.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: successful reusable `release-candidate.yml` run and `release-dist` artifact.
- Produces: TestPyPI and PyPI releases of the exact tested wheel/sdist digests.
- Prevents: rebuilding, mutating, or selecting a different artifact after release tests.

- [ ] **Step 1: Add a digest verification utility**

Create `scripts/verify_release_artifact.py`:

```python
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    value.update(path.read_bytes())
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.manifest.read_text(encoding="utf-8"))
    actual = {path.name: digest(path) for path in sorted(args.dist.iterdir()) if path.suffix in {".whl", ".gz"}}
    if actual != expected["sha256"]:
        raise SystemExit(f"release artifact digest mismatch: expected={expected['sha256']} actual={actual}")
    print("Release artifacts match tested SHA-256 manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Make publish consume, never rebuild**

Replace the build job in `.github/workflows/publish.yml` with a call to the reusable release-candidate workflow. The publish jobs download `release-dist` and `release-evidence`; they do not check out source or invoke `python -m build`.

- [ ] **Step 3: Verify the digest before each promotion**

Before TestPyPI and PyPI publish actions, run:

```yaml
      - run: python scripts/verify_release_artifact.py --dist dist --manifest release-evidence/artifact-manifest.json
```

Because publish jobs do not check out source, package `verify_release_artifact.py` inside the `release-evidence` artifact and execute that copy, or perform the equivalent inline `sha256sum -c` from the signed manifest. Use the same mechanism in both jobs.

- [ ] **Step 4: Smoke the exact TestPyPI version safely**

After TestPyPI upload:

```bash
python -m venv /tmp/testpypi-smoke
/tmp/testpypi-smoke/bin/pip install --index-url https://pypi.org/simple dist/retrieval_observatory-*.whl[dashboard,mcp]
cd /tmp
/tmp/testpypi-smoke/bin/python "$GITHUB_WORKSPACE/release-evidence/smoke_wheel.py" --expected-version "$VERSION" --output "$GITHUB_WORKSPACE/release-evidence/testpypi-smoke.json"
curl -fsS "https://test.pypi.org/pypi/retrieval-observatory/${VERSION}/json" > release-evidence/testpypi-metadata.json
```

The install uses the exact uploaded local wheel plus dependencies from PyPI, avoiding dependency confusion from TestPyPI.

- [ ] **Step 5: Verify PyPI metadata and digest after production publication**

Fetch `https://pypi.org/pypi/retrieval-observatory/${VERSION}/json`, locate the uploaded wheel and sdist, and assert their published `digests.sha256` values equal `artifact-manifest.json` before marking the workflow successful.

- [ ] **Step 6: Contract-test publish workflow structure**

Create `tests/contracts/test_publish_workflow.py`:

```python
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_publish_workflow_does_not_rebuild() -> None:
    raw = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "python -m build" not in raw
    assert "release-dist" in raw
    assert raw.count("verify_release_artifact.py") >= 2


def test_publish_workflow_has_ordered_environments() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert jobs["publish-testpypi"]["environment"] == "testpypi"
    assert jobs["publish-pypi"]["environment"] == "pypi"
    assert jobs["publish-pypi"]["needs"] == "publish-testpypi"
```

- [ ] **Step 7: Run release workflow contract tests**

```bash
pytest tests/contracts/test_publish_workflow.py -v
```

Expected: 2 passed; publish workflow cannot rebuild and PyPI promotion requires TestPyPI.

- [ ] **Step 8: Commit immutable artifact promotion**

```bash
git add CHANGELOG.md .github/workflows/publish.yml scripts/verify_release_artifact.py tests/contracts/test_publish_workflow.py docs/informative/PYPI_PUBLISH.md
git commit -m "ci: promote the tested release artifact by digest"
```

---

### Task 9: Rewrite Public Documentation Around One Factual Journey

**Files:**
- Rewrite: `README.md`
- Rewrite: `docs/START.md`
- Rewrite: `docs/WORKFLOW.md`
- Modify: `docs/CONCEPTS.md`
- Modify: `docs/REFERENCE.md`
- Modify: `docs/USAGE.md`
- Modify: `docs/ARCHITECTURE.md`
- Rewrite: `docs/INTEGRATIONS.md`
- Rewrite: `docs/integrations/AGENT_QUICKSTART.md`
- Rewrite: `docs/integrations/mcp.md`
- Modify: `docs/integrations/api.md`
- Modify: `docs/PRIVACY.md`
- Rewrite: `examples/README.md`
- Modify: `CONTRIBUTING.md`
- Modify: `SECURITY.md`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `contracts/public_surface.json`, Workstream 1 exact integration JSON schemas, Workstream 2 identity/store contract, Workstream 3 safety limits, Workstreams 6–7 final routes and evidence types.
- Produces: one install/integrate/verify/evaluate/investigate story whose commands execute verbatim from the wheel.
- Constraint: documentation names unavailable evidence and support limits; it does not call patch planning “one-step wiring” unless apply and verify complete successfully.

- [ ] **Step 1: Rewrite README as a short executable entrypoint**

Use this order:

```text
1. What retobs is and is not
2. Install
3. Integrate an existing project: plan -> review -> apply -> verify
4. Evaluate a callable
5. Open the loopback dashboard
6. What evidence retobs records
7. Supported integration tiers
8. Privacy and production-safety boundary
9. Links to task docs, reference, contributing, security, and releases
```

The primary commands are:

```bash
pip install "retrieval-observatory[dashboard,mcp]"
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --plan retobs/integration-plan.json
retobs evaluate mypackage.search:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl
retobs serve --db .retobs/results.db
```

- [ ] **Step 2: Make the agent runbook precise**

`docs/integrations/AGENT_QUICKSTART.md` must show one MCP transcript:

```text
integrate_project(project_root="/repo", phase="plan")
integrate_project(project_root="/repo", phase="apply", plan_path="/repo/retobs/integration-plan.json")
integrate_project(project_root="/repo", phase="verify", plan_path="/repo/retobs/integration-plan.json")
```

Document that required unresolved mappings block apply, stale precondition hashes block mutation, apply returns every changed file, reversal uses the apply record, and ready requires observed topology/candidate/telemetry evidence.

- [ ] **Step 3: Align all references and integration support claims**

`docs/INTEGRATIONS.md` must list first-class and supported-example paths exactly as `contracts/public_surface.json`. A first-class row requires detection, exact patch, apply, verification, real framework wheel-only CI, an owner, minimum/maximum tested version, and documented capability limits.

- [ ] **Step 4: Document production safety factually**

`docs/PRIVACY.md`, `SECURITY.md`, and `docs/ARCHITECTURE.md` must state:

```text
- default bind: 127.0.0.1;
- dashboard: unauthenticated and local-first;
- telemetry queue capacity and overflow policy are explicit configuration;
- sampling/drops/serialization/export failures are visible in instrumentation health;
- queries, candidates, metadata, labels, and traces may be sensitive;
- redaction occurs before enqueue/persistence according to the integration manifest.
```

- [ ] **Step 5: Align package metadata and examples**

Update `pyproject.toml` description/keywords/optional-extra comments so none advertise removed peer products or recorder generations. Update `examples/README.md` to the renamed examples from Task 6 and categorize examples by Evaluate, Integrate, Production, and Test Sets.

- [ ] **Step 6: Validate commands in clean documentation fixtures**

Add the README and agent-runbook commands to the wheel-only external harness as exact tokenized commands rather than separately maintained variants. The docs check passes only if those commands complete against `python_callable` and `fastapi_hybrid_dag`.

- [ ] **Step 7: Run documentation gates**

```bash
python scripts/check_public_vocabulary.py
python scripts/check_markdown_links.py
python scripts/check_public_surface.py
python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture python_callable --artifacts artifacts/docs-smoke
```

Expected: no removed vocabulary, no broken links/anchors, matching public surface, and the documented clean-wheel journey passes.

- [ ] **Step 8: Record the documentation reset**

Under `CHANGELOG.md` → `[Unreleased]` → `Changed`, add:

```markdown
- Public documentation and package metadata — center the installed-wheel `integrate plan/apply/verify` workflow, active task vocabulary, evidence limits, and loopback safety boundary.
```

- [ ] **Step 9: Commit public documentation**

```bash
git add CHANGELOG.md README.md CONTRIBUTING.md SECURITY.md pyproject.toml docs examples
git commit -m "docs: publish the unified integration journey"
```

---

### Task 10: Make Release Proof a Generated, Reviewable Artifact

**Files:**
- Rewrite: `docs/RELEASE_CHECKLIST.md`
- Modify: `scripts/check_release.py`
- Create: `scripts/generate_release_evidence.py`
- Create: `tests/contracts/test_release_evidence.py`
- Modify: `.github/workflows/release-candidate.yml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all source, wheel, external fixture, store, UI, browser, documentation, and digest results.
- Produces: `artifacts/release-evidence.json` and `artifacts/release-evidence.md` with command, status, artifact path, digest, and timestamp for every gate.
- Enforces: no manual checkbox can substitute for a missing machine result.

- [ ] **Step 1: Define the evidence schema in a contract test**

Create `tests/contracts/test_release_evidence.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


REQUIRED_GATES = {
    "public_surface",
    "removed_vocabulary",
    "markdown_links",
    "ruff",
    "python_unit_contracts",
    "python_integration",
    "sqlite_store",
    "postgres_store",
    "ui_vitest",
    "ui_build",
    "browser_desktop_mobile",
    "wheel_metadata",
    "wheel_smoke",
    "external_python",
    "external_fastapi",
    "external_langchain",
    "external_llamaindex",
    "artifact_digest",
}


def test_release_evidence_has_every_passing_gate(release_evidence_path: Path) -> None:
    evidence = json.loads(release_evidence_path.read_text(encoding="utf-8"))
    gates = {gate["id"]: gate for gate in evidence["gates"]}
    assert REQUIRED_GATES <= gates.keys()
    assert all(gates[name]["status"] == "passed" for name in REQUIRED_GATES)
    assert all(gates[name]["command"] for name in REQUIRED_GATES)
    assert all(gates[name]["artifacts"] for name in REQUIRED_GATES)
    assert evidence["distribution"]["sha256"]
    assert evidence["version"] == evidence["distribution"]["version"]
```

- [ ] **Step 2: Generate release evidence from job result files**

`scripts/generate_release_evidence.py` accepts `--results-dir`, `--dist`, `--output-json`, and `--output-markdown`. It fails if a required result is missing, failed, skipped, or references a different wheel digest. The Markdown begins with:

```markdown
# retobs release evidence

- Version: `<version>`
- Wheel SHA-256: `<digest>`
- Source commit: `<commit>`
- Generated: `<UTC timestamp>`

| Gate | Status | Command | Evidence artifact |
|---|---|---|---|
```

- [ ] **Step 3: Strengthen `check_release.py`**

Add options:

```text
--require-assets
--require-wheel PATH
--require-evidence PATH
```

The check must verify:

```text
pyproject version == wheel METADATA version == runtime version == demo asset version == release evidence version
public surface checker passes
removed vocabulary checker passes
Markdown link/anchor checker passes
wheel contains UI and canonical examples
wheel excludes renamed/removed examples and migration docs
release evidence contains every required passing gate for the same SHA-256
[Unreleased] contains Added/Changed/Fixed/Removed headings needed by current diff
```

- [ ] **Step 4: Replace manual checklist claims with evidence gates**

Rewrite `docs/RELEASE_CHECKLIST.md` to explain exact commands and the generated evidence artifact. Keep only external actions as manual confirmations: trusted-publisher environment approval, private vulnerability disclosure review, and release-note approval. Remove migration-warning and old-fixture-read requirements.

- [ ] **Step 5: Assemble evidence in release-candidate CI**

The final job downloads all result artifacts, verifies their wheel digest, runs:

```bash
python scripts/generate_release_evidence.py --results-dir results --dist dist --output-json artifacts/release-evidence.json --output-markdown artifacts/release-evidence.md
python scripts/check_release.py --require-assets --require-wheel dist/retrieval_observatory-*.whl --require-evidence artifacts/release-evidence.json
```

Then upload `release-evidence` and append the Markdown to `$GITHUB_STEP_SUMMARY`.

- [ ] **Step 6: Run the complete local release proof**

```bash
ruff check retrieval_observatory tests scripts
pytest tests/unit tests/contracts -v --tb=short
pytest tests/integration -v --tb=short
npm ci --prefix retrieval_observatory/dashboard/ui
npm run test --prefix retrieval_observatory/dashboard/ui -- --run
npm run build --prefix retrieval_observatory/dashboard/ui
python -m build
twine check dist/*
python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture all --artifacts artifacts/external-fixtures
python scripts/check_release.py --require-assets --require-wheel dist/retrieval_observatory-*.whl --require-evidence artifacts/release-evidence.json
git diff --check
git status --short
```

Expected: every command exits `0`; four external fixtures pass; release evidence references the exact wheel digest; `git diff --check` emits no output; `git status --short` contains only intended workstream changes.

- [ ] **Step 7: Commit generated release proof support**

```bash
git add CHANGELOG.md docs/RELEASE_CHECKLIST.md scripts/check_release.py scripts/generate_release_evidence.py tests/contracts/test_release_evidence.py .github/workflows/release-candidate.yml
git commit -m "release: require generated end-to-end evidence"
```

---

## Final Acceptance Gates

The workstream is complete only when all statements below have current release-candidate evidence:

- [ ] `retobs --help` exposes exactly the approved task commands; each removed command returns nonzero with “No such command,” not a warning.
- [ ] MCP tool discovery equals `contracts/public_surface.json`; no alias or descriptor tools remain.
- [ ] `retrieval_observatory.__all__` equals the approved SDK exports; no legacy recorder, snapshot, benchmark, or wiring alias remains.
- [ ] Active source, tests, examples, and public documentation contain no forbidden vocabulary outside explicit immutable-history exclusions.
- [ ] README and agent-runbook commands execute verbatim from a wheel-only environment.
- [ ] Python, FastAPI hybrid DAG, LangChain, and LlamaIndex external projects complete plan, apply, and verify through the installed wheel.
- [ ] The FastAPI fixture records stable operator IDs, exact expected edges, gate-skip/error topology variants, and candidate transitions across repeated queries.
- [ ] A production trace without an evaluation Run appears in Production APIs and passes the production capability checks.
- [ ] Telemetry enabled, disabled, overflowed, serialization-failed, and exporter-failed modes never change application response status/body; health counters explain every loss.
- [ ] SQLite and PostgreSQL execute the same unified trace/store contract suite.
- [ ] Vitest, production build/bundle budgets, Playwright desktop/mobile, accessibility, route persistence, and console/API error checks pass against the wheel-installed server.
- [ ] Wheel contents include the built dashboard and canonical examples, and exclude removed/migration material.
- [ ] Tag, `pyproject.toml`, runtime version, wheel metadata, generated assets, documentation examples, and release evidence report the same version.
- [ ] TestPyPI and PyPI receive the exact SHA-256-identified wheel and sdist tested by release-candidate CI; no downstream rebuild occurs.
- [ ] `docs/RELEASE_CHECKLIST.md` links every required gate to machine evidence, with manual approval limited to external governance actions.
- [ ] `CHANGELOG.md` records every user-visible addition, change, fix, and removal under `[Unreleased]` without rewriting historical releases.
- [ ] `git diff --check` passes and the repository contains no unintended generated files, databases, virtual environments, or credentials.

## Plan Self-Review

- **Spec coverage:** Public-surface convergence, immediate deletion, vocabulary enforcement, four external repositories, wheel isolation, FastAPI default tracing, production-only visibility, application non-interference, CI, immutable artifact promotion, documentation, and generated release evidence each map to a task and an acceptance gate.
- **July 13 overlap retained:** Cross-surface contract testing, real hybrid golden fixtures, live-framework CI, clean-wheel callable smoke, browser/accessibility gates, link checks, generated assets, and PR Markdown/HTML comparison artifacts remain required.
- **July 13 compatibility direction rejected:** Migration aliases, warning wrappers, dual reads, old fixture reads, V1 adapters, and delayed removal are explicitly absent because the approved beta reset requires immediate deletion.
- **Placeholder scan:** The plan contains no deferred implementation markers or unspecified error-handling steps. Every implementation step names files, behavior, commands, and expected results.
- **Type consistency:** Integration, verification, telemetry-health, trace, public-surface, fixture, digest, and release-evidence names are consistent with the dependency contract and approved design.
- **Boundary check:** This workstream validates contracts owned by Workstreams 1–7 and does not recreate their integration, storage, telemetry, diagnostic, dashboard, or analysis implementations.
