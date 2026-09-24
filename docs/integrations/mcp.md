# MCP

Install and register the MCP server:

```bash
pip install "retrieval-observatory[mcp]"
```

```json
{
  "mcpServers": {
    "retobs": { "command": "retobs", "args": ["mcp"] }
  }
}
```

`integrate_project(project_root, phase, plan=None, plan_path=None, db_path=".retobs/results.db", framework=None)` runs one phase of the reviewed integration loop:

| Phase | Input | Result |
|---|---|---|
| `plan` | nothing, or `plan_path` (or `plan`) of a reviewed plan | The static proposal, or a re-plan that takes the reviewed operators, scenarios, identity and judgments verbatim and regenerates patches, actions, `expected_capabilities` and `open_questions`. `discovery.runbook` names the packaged runbook. |
| `apply` | `plan_path` (or `plan`), required | Patches the listed files, writes `retobs/integration.yaml`; refuses on `unresolved` entries, a stale content hash, an already-applied plan, or a `capture` symbol missing from `retobs_adapter.py`. |
| `verify` | optional `plan_path`, which must carry the applied `plan_id` | `status` (`ready \| partial \| failed`), one entry per capability (`status`, `evidence`, `scope`, `failures[]` with `code`, `detail`, `fix`, `op_id`), `observed_operator_ids`, `topology_variants`, `telemetry_health`. It also persists an `integration` record in the database that Connect reads. |
| `revert` | nothing | Restores every file apply patched and removes the manifest; refuses if one of them changed since apply. `retobs/integration-plan.json` is kept. |

A relative `db_path` resolves against `project_root`. `framework` overrides detection (`python`, `fastapi`, `langchain`, `llamaindex`, `http`). Verify without a manifest fails with `no retobs/integration.yaml: run apply first`; verify without traces names the `service_id`, `pipeline_id` and database it looked for.

MCP is a transport: the server grants no filesystem access of its own and does not replace source instrumentation. The plan is a file the agent edits with its own tools, and a `CaptureSpec` lives in the project's root `retobs_adapter.py`. `describe_integration()` returns the runbook's installed path as `runbook_path`. See [AGENT_QUICKSTART.md](AGENT_QUICKSTART.md) for the whole loop.

The release-gated tool inventory is `evaluate`, `evaluate_file`, `compare`, `inspect_query`, `inspect_document`, `get_report`, `describe_config`, `validate_config`, `integrate_project`, `verify_integration`, `push_traces`, and `get_pipeline_graph`. `compare` with `format="audit"` returns the same `audit-1` release audit as `retobs compare --artifacts`.

MCP results preserve evidence limits: a missing candidate transition, unsupported integration mapping, or failed exporter stays unavailable or failed rather than becoming a quality claim.
