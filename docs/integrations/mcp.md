# MCP server — agent integration

retobs ships an [MCP](https://modelcontextprotocol.io) server so an agent (Claude Code, Cursor,
Codex, etc.) can benchmark retrieval configs, wire integrations, and read results directly.
Install the extra and run it over stdio:

```bash
pip install 'retrieval-observatory[mcp]'
retobs mcp init
retobs doctor
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

Recommended loop: `describe_config` → fill the example → `validate_config` → `benchmark_config` /
`benchmark_vs_baseline`. For on-disk YAML in an external project, use `benchmark_config_file`.

### Integration wiring — start here

| Tool | Params | Returns |
|---|---|---|
| **`wire_project`** | `project_root`, `framework?`, `phase?` (`setup` \| `verify`) | **One-step wiring:** scaffold, manifest, `RETOS.md`, `wiring_brief`; verify returns `status: ready` |
| `describe_integration` | `framework?` | Snippets for manual wiring |
| `bootstrap_project` | *(deprecated)* | Alias of `wire_project(phase=setup)` |
| `push_traces` | `run_id`, `traces` | Ingest V2 traces |
| `verify_integration` | `run_id?`, `expected_stages?` | Trace/metrics check |

CLI twin: **`retobs wire .`** then **`retobs wire . --verify`**

### Run & read

| Tool | Params | Returns |
|---|---|---|
| `list_runs` | `db_path?` | `[{run_id, experiment_name, started_at, finished_at}]` |
| `get_run_metrics` | `run_id`, `db_path?` | aggregated metrics (mean + CI per stage/metric) |
| `benchmark_config` | `config`, `max_queries?`, `db_path?`, `config_base_dir?` | `{run_id, metrics, headline_winner}` |
| `benchmark_config_file` | `config_path` (absolute YAML path), `max_queries?`, `db_path?` | Same as `benchmark_config` with CLI path/sys.path semantics |
| `benchmark_vs_baseline` | `candidate_config`, `baseline_run_id?` \| `baseline_config?`, `max_queries?`, `db_path?`, `config_base_dir?` | `{baseline_run_id, candidate_run_id, regressions, significant}` |
| `get_pareto_frontier` | `run_id`, `db_path?` | Pareto-optimal pipelines + frontier order |
| `get_recommendations` | `run_id`, `db_path?` | Advisor recommendations |
| `get_operator_attribution` | `run_id`, `metric?`, `k?`, `db_path?` | per-operator marginal contribution + CIs |
| `get_pipeline_diagram` | `run_id`, `db_path?` | per-stage diagram nodes with metric CIs |
| `get_pipeline_graph` | `run_id`, `db_path?` | canonical DAG graph (same contract as REST `/pipeline-graph`) |

`config` / `baseline_config` / `candidate_config` are `ExperimentConfig` JSON (adapter specs). See
[api.md](api.md) for the config shape.

`benchmark_pipeline_descriptor` is deprecated — pass the same shape to `benchmark_config`.

## Example agent prompts

**Benchmark a config:**

> Call describe_config, build a config with adapter.http pointing at my service, validate it,
> then benchmark_config with max_queries=20.

**Wire retobs into my Python RAG repo:**

> bootstrap_project(project_root='/path/to/my-rag', framework='python'), then
> benchmark_config_file(config_path='.../retobs/config.yaml'), then describe_integration for tracing.

**Regression check:**

> Benchmark this BM25 config against run `7069d650` on `.retobs/results.db` and tell me if it
> regressed Recall@10.

The agent calls `benchmark_vs_baseline(candidate_config=…, baseline_run_id="7069d650")` and reads
the `regressions` + `significant` fields.
