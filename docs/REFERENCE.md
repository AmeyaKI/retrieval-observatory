# Reference

## CLI

| Command | Purpose |
|---|---|
| `retobs integrate ROOT --phase plan|apply|verify` | Plan, apply a reviewed plan, or verify observed integration evidence. |
| `retobs evaluate TARGET` | Evaluate `module:symbol` or `file.py:symbol`; use `--config` for advanced YAML. |
| `retobs compare BASELINE CANDIDATE` | Produce a validity-gated paired comparison. |
| `retobs inspect-query RUN QUERY` | Render scoped query evidence. |
| `retobs report RUN` | Render one canonical Run report. |
| `retobs production` | Inspect persisted production trace evidence. |
| `retobs testsets` | Manage Test Set evidence. |
| `retobs serve` | Serve the local dashboard on `127.0.0.1` by default. |

The supported command inventory is release-gated by `contracts/public_surface.json`.

## SDK

The supported SDK exports are `evaluate`, `compare`, `inspect_query`, `init`, `generate_testset`, and their public models: `Comparison`, `Document`, `IntegrationOptions`, `Query`, `QueryEvidence`, `RetrievalTrace`, `Run`, `TestSet`, and `TraceRecorder`.

## MCP

The MCP inventory is release-gated too. Use `integrate_project`, `evaluate`, `compare`, `inspect_query`, `get_report`, `get_pipeline_graph`, `push_traces`, `verify_integration`, `describe_config`, `validate_config`, or `evaluate_file`. See [MCP](integrations/mcp.md).
