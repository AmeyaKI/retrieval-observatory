# MCP server — agent integration

retobs ships an [MCP](https://modelcontextprotocol.io) server so an agent (Claude Code, Cursor,
Codex, etc.) can benchmark retrieval configs, wire integrations, and read results directly.
Install the extra and run it over stdio:

```bash
pip install 'retrieval-observatory[mcp]'
retobs mcp init
retobs verify .
```

## Register with your agent

**Claude Desktop / Claude Code:**

```jsonc
{
  "mcpServers": {
    "retobs": { "command": "retobs", "args": ["mcp"] }
  }
}
```

**Cursor** (`.cursor/mcp.json` in your project or global settings):

```jsonc
{
  "mcpServers": {
    "retobs": { "command": "retobs", "args": ["mcp"] }
  }
}
```

Run `retobs mcp` from a directory that contains `retobs-mcp.yaml`, or pass defaults via env.
`retobs-mcp.yaml` sets `db_path`, `max_queries`, and optional `baseline_run_id`.

Primary runbook: [AGENT_QUICKSTART.md](AGENT_QUICKSTART.md).

## Tools

Runs default to **bounded-synchronous** with a small `max_queries` cap (50) so a tool call returns
within an agent's timeout. For large runs use the REST job model ([api.md](api.md)).

### Self-describing config (no external docs needed)

| Tool | Params | Returns |
|---|---|---|
| `describe_config` | — | ExperimentConfig JSON schema + runnable `example_config` + per-adapter/dataset snippets + notes |
| `validate_config` | `config` | `{valid, status, items}` — dry-run validation, no benchmark run |

Recommended loop: `describe_config` → fill the example → `validate_config` → `evaluate` →
`get_report`. For on-disk YAML in an external project, use `evaluate_file`.

### Integration wiring — start here

| Tool | Params | Returns |
|---|---|---|
| **`wire_project`** | `project_root`, `framework?`, `phase?` (`setup` \| `verify`) | **One-step wiring:** scaffold, manifest, `RETOS.md`, `wiring_brief`; verify returns `status: ready` |
| `describe_integration` | `framework?` | Snippets for manual wiring |
| `bootstrap_project` | *(deprecated)* | Alias of `wire_project(phase=setup)` |
| `push_traces` | `run_id`, `traces` | Ingest V2 traces |
| `verify_integration` | `run_id?`, `expected_stages?` | Trace/metrics check |

CLI twin: **`retobs integrate . --plan`**, apply the returned minimal patches, then
**`retobs verify .`**.

### Run & read

| Tool | Params | Returns |
|---|---|---|
| `list_runs` | `db_path?` | `[{run_id, experiment_name, started_at, finished_at}]` |
| `get_run_metrics` | `run_id`, `db_path?` | aggregated metrics (mean + CI per stage/metric) |
| `evaluate` / `evaluate_file` | config or config path | Canonical bounded evaluation result |
| `compare` | baseline/candidate run IDs | Validity-gated paired comparison report |
| `inspect_query` | run/query IDs | Scoped QueryEvidence document |
| `get_report` | run ID and format | Canonical JSON/Markdown/HTML report |
| `get_operator_attribution` | `run_id`, `metric?`, `k?`, `db_path?` | per-operator marginal contribution + CIs |
| `get_pipeline_graph` | `run_id`, `db_path?` | canonical DAG graph (same contract as REST `/pipeline-graph`) |

`config` / `baseline_config` / `candidate_config` are `ExperimentConfig` JSON (adapter specs). See
[api.md](api.md) for the config shape.

Legacy `benchmark_config`, `benchmark_config_file`, `benchmark_vs_baseline`,
`benchmark_pipeline_descriptor`, `get_pareto_frontier`, `get_recommendations`, and
`get_pipeline_diagram` remain migration aliases until v1.0. New integrations should use the
task-oriented tools above.

## Example agent prompts

**Evaluate a config:**

> Call describe_config, build a config with adapter.http pointing at my service, validate it,
> then evaluate with max_queries=20 and render get_report as Markdown.

**Wire retobs into my Python RAG repo:**

> plan_integration(project_root='/path/to/my-rag'), apply the minimal patches, verify_integration,
> then evaluate_file(config_path='.../retobs/config.yaml').

**Regression check:**

> Evaluate this BM25 config and compare it with baseline run `7069d650` on `.retobs/results.db`.
> regressed Recall@10.

The agent calls `evaluate`, then `compare(baseline_run_id="7069d650", candidate_run_id=…)` and
reads the canonical validity, corrected statistics, affected queries, and verdict.
