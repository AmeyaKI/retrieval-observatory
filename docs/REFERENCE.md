# Reference

## CLI

| Command | Purpose |
|---|---|
| `retobs integrate ROOT --phase plan\|apply\|verify\|revert` | Plan (or re-plan with `--plan`), apply a reviewed plan, verify eight capabilities from observed traces (`--db`, optional `--policy` preflight), or revert. `--framework` overrides detection. |
| `retobs evaluate TARGET` | Evaluate `module:symbol` or `file.py:symbol` with `--queries`, `--qrels`, `--corpus`, `--k`, `--name`, `--db`, `--provenance KEY=VALUE`, `--chunk-map PATH`; `--config` for advanced YAML. |
| `retobs inspect-query RUN QUERY` | One query's evidence in a Run. |
| `retobs inspect-document RUN ENTITY` | One entity's (`namespace:id`) journey across every query of a Run; `--pipeline`, `--k`, `--unit document\|chunk`, `--format json`. |
| `retobs compare BASELINE CANDIDATE --policy POLICY` | The release audit. `--artifacts DIR` writes `release-audit.json` and `release-audit.html`; `--format terminal\|json\|markdown\|html` with `--output`; `--fail-on never\|fail\|hold-or-block-or-fail`. |
| `retobs report RUN` | One Run's report. |
| `retobs storage migrate --db PATH` | Additive schema upgrade to v3; backs the file up first (`--no-backup` to skip). |
| `retobs storage index RUN --db PATH` | Build a Run's investigation rows (`--pipeline`, `--k`, `--unit`). |
| `retobs demo` | Two deterministic demo Runs, `demo_manifest.json`, and a v3 policy. |
| `retobs serve` | The dashboard on `127.0.0.1:4000` by default (`--db`, repeatable). |
| `retobs mcp` | The MCP server; `retobs mcp init` writes a starter config. |

The command inventory is release-gated by `contracts/public_surface.json`.

`retobs compare` exit status: `0` PASS (or not gated), `1` FAIL, `2` BLOCK, `3` HOLD when
`--fail-on` selects the decision (`hold-or-block-or-fail` selects all three, `fail` only FAIL,
`never` none); `64` invalid `--fail-on` or `--format`; `70` the comparison could not be produced.
Without `--policy` the decision is `HOLD`. See
[retrieval release decisions](guides/retrieval-release-decisions.md#exit-codes).

## Dashboard

`#/investigate?db=&run=&pipeline=&view=queries|documents&query=&trace=&entity=&stage=&outcome=&compare=`,
`#/connect?db=&integration=`, `#/audit?db=&baseline=&candidate=&policy=`, and `#/help`. Links from
0.6.0 redirect for one release; see [migrating to focused retobs](guides/migrating-to-focused-retobs.md#dashboard-links).

## SDK

`retrieval_observatory` exports `evaluate`, `compare`, `inspect_query`, `inspect_document`,
`init`, and the models `Comparison`, `Document`, `IntegrationOptions`, `Query`, `QueryEvidence`,
`RetrievalTrace`, `Run`, and `TraceRecorder`. Instrumentation lives in
`retrieval_observatory.sdk.observe` (`observe`, `trace_scope`, `observe_gate`). The synthetic
test-set API was removed in 0.7.0 with no replacement.

## MCP

The release-gated tools are `integrate_project`, `verify_integration`, `evaluate`,
`evaluate_file`, `compare`, `inspect_query`, `inspect_document`, `get_report`,
`get_pipeline_graph`, `push_traces`, `describe_config`, and `validate_config`. See
[MCP](integrations/mcp.md).
