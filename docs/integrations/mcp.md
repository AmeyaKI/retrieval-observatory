# MCP server — agent integration

retobs ships an [MCP](https://modelcontextprotocol.io) server so an agent (Claude, etc.) can
benchmark retrieval configs and read results directly. Install the extra and run it over stdio:

```bash
pip install 'retrieval-observatory[mcp]'
retobs mcp
```

Register it with an MCP client, e.g. Claude Desktop:

```jsonc
{
  "mcpServers": {
    "retobs": { "command": "retobs", "args": ["mcp"] }
  }
}
```

## Tools

Runs default to **bounded-synchronous** with a small `max_queries` cap (50) so a tool call returns
within an agent's timeout. For large runs use the REST job model ([api.md](api.md)).

**Start here (self-describing — no external docs needed):**

| Tool | Params | Returns |
|---|---|---|
| `describe_config` | — | ExperimentConfig JSON schema + runnable `example_config` + per-adapter/dataset snippets + notes |
| `validate_config` | `config` | `{valid, status, items}` — dry-run validation, no benchmark run |

Recommended loop: `describe_config` → fill the example → `validate_config` → `benchmark_config` /
`benchmark_vs_baseline`. This is fully self-guided and never touches your live pipeline.

**Run & read:**

| Tool | Params | Returns |
|---|---|---|
| `list_runs` | `db_path?` | `[{run_id, experiment_name, started_at, finished_at}]` |
| `get_run_metrics` | `run_id`, `db_path?` | aggregated metrics (mean + CI per stage/metric) |
| `benchmark_config` | `config`, `max_queries?`, `db_path?` | `{run_id, metrics, headline_winner}` |
| `benchmark_vs_baseline` | `candidate_config`, `baseline_run_id?` \| `baseline_config?`, `max_queries?`, `db_path?` | `{baseline_run_id, candidate_run_id, regressions, significant}` |
| `get_pareto_frontier` | `run_id`, `db_path?` | Pareto-optimal pipelines + frontier order |
| `get_recommendations` | `run_id`, `db_path?` | Advisor recommendations |
| `get_operator_attribution` | `run_id`, `metric?`, `k?`, `db_path?` | per-operator marginal contribution + CIs |
| `get_pipeline_diagram` | `run_id`, `db_path?` | per-stage diagram nodes with metric CIs |

`config` / `baseline_config` / `candidate_config` are `ExperimentConfig` JSON (adapter specs). See
[api.md](api.md) for the config shape.

## Example agent prompt

> Benchmark this BM25 config against run `7069d650` on `.retobs/results.db` and tell me if it
> regressed Recall@10.

The agent calls `benchmark_vs_baseline(candidate_config=…, baseline_run_id="7069d650")` and reads
the `regressions` + `significant` fields.
