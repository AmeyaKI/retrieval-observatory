# Task reference

## CLI

| Command | Purpose |
|---|---|
| `retobs evaluate TARGET` | Evaluate `module:symbol` or `file.py:symbol`. |
| `retobs evaluate --config FILE` | Evaluate an advanced YAML config. |
| `retobs compare BASELINE CANDIDATE` | Validity-gated paired comparison. |
| `retobs inspect-query RUN QUERY` | Print scoped query evidence. |
| `retobs report RUN` | Render the canonical run report. |
| `retobs integrate . --plan` | Inspect a project and propose the smallest patch. |
| `retobs verify` | Verify integration evidence and capability readiness. |
| `retobs serve` | Serve the local dashboard/API. |
| `retobs testsets generate` | Generate a corpus-derived Test Set. |
| `retobs production stats` | Summarize sampled production traces. |

All report commands accept machine-readable JSON. `compare --fail-on regression-or-no-decision` is the strict CI gate.

## SDK

- `ro.evaluate(...)` and `ro.benchmark(...)` return `BenchmarkReport`; `evaluate` is the task-oriented name.
- `ro.run_from_config(...)` runs the advanced config contract.
- `report.to_json()`, `.to_markdown()`, `.to_html()`, and `.write(...)` use one `ReportModel`.
- `ro.generate_testset(...)` creates an in-memory Test Set; its label provenance depends on the selected generator/judge.
- `ro.init(...)` and V2 tracing integrations record production operator DAGs.

## MCP

Task-oriented tools are `evaluate`, `evaluate_file`, `compare`, `inspect_query`, `get_report`, `plan_integration`, and `verify_integration`. Low-level compatibility tools remain available for existing agents. See [MCP integration](integrations/mcp.md).

## API scope

Evidence endpoints use `/dbs/{db_id}/...`. Cross-database comparison requires explicit selections with database and Run IDs. The legacy single-database aliases are compatibility surfaces, not a license to mix evidence.

## Advanced configuration

Use [YAML_GUIDE.md](YAML_GUIDE.md) for adapters, declarative DAGs, caching, timeouts, metrics, and stores.
