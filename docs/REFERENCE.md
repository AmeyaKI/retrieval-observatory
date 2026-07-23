# Reference

## CLI

| Command | Purpose |
|---|---|
| `retobs integrate ROOT --phase plan|apply|verify` | Plan, apply a reviewed plan, or verify observed integration evidence. |
| `retobs evaluate TARGET` | Evaluate `module:symbol` or `file.py:symbol`; use `--config` for advanced YAML. |
| `retobs compare BASELINE CANDIDATE --policy POLICY` | Produce the canonical policy-bounded `PASS`/`HOLD`/`BLOCK`/`FAIL` comparison artifact. |
| `retobs inspect-query RUN QUERY` | Render scoped query evidence. |
| `retobs report RUN` | Render one canonical Run report. |
| `retobs production` | Inspect persisted production trace evidence. |
| `retobs testsets` | Manage Test Set evidence. |
| `retobs serve` | Serve the local dashboard on `127.0.0.1` by default. |

The supported command inventory is release-gated by `contracts/public_surface.json`.

`--fail-on fail` exits nonzero only for `FAIL`; `--fail-on hold-or-block-or-fail` exits nonzero for any non-pass decision. Without `--policy`, comparison fields remain available but the release decision is `HOLD`. Policies are local YAML with exact metric keys and exact top-level slice values. See [retrieval release decisions](guides/retrieval-release-decisions.md).

## SDK

The supported SDK exports are `evaluate`, `compare`, `inspect_query`, `init`, `generate_testset`, and their public models: `Comparison`, `Document`, `IntegrationOptions`, `Query`, `QueryEvidence`, `RetrievalTrace`, `Run`, `TestSet`, and `TraceRecorder`.

## MCP

The MCP inventory is release-gated too. Use `integrate_project`, `evaluate`, `compare`, `inspect_query`, `get_report`, `get_pipeline_graph`, `push_traces`, `verify_integration`, `describe_config`, `validate_config`, or `evaluate_file`. See [MCP](integrations/mcp.md).
