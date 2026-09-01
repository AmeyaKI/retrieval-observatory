# Agent MCP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the setup cost of wiring retobs MCP into an agent by adding a simple bootstrap path and a minimal pipeline descriptor flow.

**Architecture:** Build a thin, config-driven “easy mode” around the existing MCP server. The new flow uses a small YAML config plus a simple descriptor-based tool so agents can benchmark and compare pipelines without hand-authoring a full retobs config.

**Tech Stack:** Python, Typer CLI, FastMCP, YAML, pytest.

## Global Constraints

- Keep the current MCP tool surface and stdio transport intact.
- Make the first-time setup require as few commands as possible.
- Favor simple config over extra abstractions.
- Reuse the existing config-first benchmark execution path rather than adding a parallel implementation.

---

### Task 1: Add MCP bootstrap CLI

**Files:**
- Create: `retrieval_observatory/mcp/config.py`
- Modify: `retrieval_observatory/cli.py`
- Test: `tests/unit/test_mcp_cli.py`

**Interfaces:**
- Consumes: current `retobs mcp` command entrypoint.
- Produces: a new `retobs mcp init` command that writes a starter config file and prints ready-to-use client registration snippets.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from retrieval_observatory.cli import app
from typer.testing import CliRunner


def test_mcp_init_writes_config(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "init", "--output", str(tmp_path / "retobs-mcp.yaml")])
    assert result.exit_code == 0
    assert (tmp_path / "retobs-mcp.yaml").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_mcp_cli.py -q`
Expected: FAIL with `No such command 'init'` or equivalent.

- [ ] **Step 3: Implement the minimal CLI command**

```python
# retrieval_observatory/mcp/config.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = """db_path: .retobs/results.db
max_queries: 50
baseline_run_id: null
pipeline_name: my-pipeline
"""


def write_default_config(output_path: str | Path) -> Path:
    path = Path(output_path)
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
```

```python
# retrieval_observatory/cli.py
@app.command("init")
def mcp_init(output: str = typer.Option("retobs-mcp.yaml", "--output", help="Path to write the starter MCP config.")) -> None:
    from retrieval_observatory.mcp.config import write_default_config

    path = write_default_config(output)
    console.print(f"[green]Wrote MCP config to[/green] {path}")
    console.print("Example registration:")
    console.print('{"mcpServers": {"retobs": {"command": "retobs", "args": ["mcp"]}}}')
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_mcp_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/cli.py retrieval_observatory/mcp/config.py tests/unit/test_mcp_cli.py
git commit -m "feat: add mcp init bootstrap command"
```

### Task 2: Load a lightweight MCP config file

**Files:**
- Modify: `retrieval_observatory/mcp/server.py`
- Modify: `retrieval_observatory/cli.py`
- Test: `tests/unit/test_mcp_server.py`

**Interfaces:**
- Consumes: the new config file path from the CLI.
- Produces: default values for `db_path`, `max_queries`, and metadata so the server starts with minimal friction.

- [ ] **Step 1: Write the failing test**

```python
import os

from retrieval_observatory.mcp import server


def test_loads_simple_mcp_config(tmp_path):
    config_path = tmp_path / "retobs-mcp.yaml"
    config_path.write_text("db_path: /tmp/results.db\nmax_queries: 12\n", encoding="utf-8")
    cfg = server.load_config(str(config_path))
    assert cfg["db_path"] == "/tmp/results.db"
    assert cfg["max_queries"] == 12
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_mcp_server.py -q`
Expected: FAIL with `AttributeError` or `No such function`.

- [ ] **Step 3: Implement minimal config loading**

```python
# retrieval_observatory/mcp/server.py
import os
from pathlib import Path

import yaml


def load_config(config_path: str | None = None) -> dict[str, object]:
    if not config_path:
        return {"db_path": DEFAULT_DB_PATH, "max_queries": DEFAULT_MAX_QUERIES}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"MCP config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "db_path": data.get("db_path", DEFAULT_DB_PATH),
        "max_queries": int(data.get("max_queries", DEFAULT_MAX_QUERIES)),
        "pipeline_name": data.get("pipeline_name"),
        "baseline_run_id": data.get("baseline_run_id"),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_mcp_server.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/mcp/server.py retrieval_observatory/cli.py tests/unit/test_mcp_server.py
git commit -m "feat: load simple mcp config defaults"
```

### Task 3: Add a minimal descriptor-based benchmark tool

**Files:**
- Modify: `retrieval_observatory/mcp/server.py`
- Test: `tests/unit/test_mcp_server.py`

**Interfaces:**
- Consumes: a simple descriptor mapping with `name`, `dataset`, and `pipelines`.
- Produces: the same benchmark result payload returned by `benchmark_config`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_benchmark_pipeline_descriptor(tmp_path):
    db_path = str(tmp_path / "descriptor.db")
    descriptor = {
        "name": "descriptor-test",
        "dataset": {
            "type": "custom",
            "queries_path": os.path.join(FIXTURES, "tiny_queries.jsonl"),
            "corpus_path": os.path.join(FIXTURES, "tiny_corpus.jsonl"),
        },
        "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
    }
    result = await server._benchmark_pipeline_descriptor(descriptor, db_path=db_path, max_queries=5)
    assert result["run_id"]
    assert result["metrics"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_mcp_server.py -q`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement the descriptor wrapper**

```python
async def _benchmark_pipeline_descriptor(
    descriptor: dict[str, object],
    max_queries: int = DEFAULT_MAX_QUERIES,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, object]:
    config = {
        "experiment": {"name": str(descriptor.get("name", "mcp-pipeline"))},
        "dataset": descriptor.get("dataset", {}),
        "pipelines": descriptor.get("pipelines", []),
        "output": {"store": "sqlite", "db_path": db_path},
    }
    return await _benchmark_config(config, max_queries=max_queries, db_path=db_path)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_mcp_server.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add retrieval_observatory/mcp/server.py tests/unit/test_mcp_server.py
git commit -m "feat: add descriptor-based mcp benchmark tool"
```

### Task 4: Document and example the new path

**Files:**
- Modify: `docs/integrations/mcp.md`
- Modify: `docs/USAGE.md`
- Create: `examples/integrations/mcp_agent_quickstart.yaml`

**Interfaces:**
- Consumes: the new CLI flow and descriptor tool.
- Produces: simple, copy-paste documentation for agents and operators.

- [ ] **Step 1: Write the new documentation**

Add a section titled “Fastest way to connect an agent” with:

```bash
pip install 'retrieval-observatory[mcp]'
retobs mcp init
retobs mcp
```

And a short example descriptor JSON snippet for the new tool.

- [ ] **Step 2: Add the example config**

```yaml
db_path: .retobs/results.db
max_queries: 50
pipeline_name: my-pipeline
```

- [ ] **Step 3: Verify the docs mention the new entrypoint**

Run: `grep -R "mcp init" docs retrieval_observatory`
Expected: matches in docs and CLI help text.

- [ ] **Step 4: Commit**

```bash
git add docs/integrations/mcp.md docs/USAGE.md examples/integrations/mcp_agent_quickstart.yaml
git commit -m "docs: add easy mcp integration guide"
```

### Task 5: Add a small regression test for the new flow

**Files:**
- Modify: `tests/unit/test_mcp_server.py`

**Interfaces:**
- Consumes: the new CLI and server helpers.
- Produces: confidence that the simple path keeps working.

- [ ] **Step 1: Write the regression test**

```python
def test_mcp_init_and_descriptor_flow(tmp_path):
    cfg_path = tmp_path / "retobs-mcp.yaml"
    write_default_config(cfg_path)
    cfg = server.load_config(str(cfg_path))
    assert cfg["db_path"]
```

- [ ] **Step 2: Run the test suite for MCP**

Run: `pytest tests/unit/test_mcp_server.py tests/unit/test_mcp_cli.py -q`
Expected: PASS.
