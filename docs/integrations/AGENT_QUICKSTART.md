# Agent integration runbook

Register the MCP server with `retobs mcp`, then run one reviewed integration loop:

```text
integrate_project(project_root="/repo", phase="plan")
integrate_project(project_root="/repo", phase="apply", plan_path="/repo/retobs/integration-plan.json")
integrate_project(project_root="/repo", phase="verify", plan_path="/repo/retobs/integration-plan.json")
```

The plan result contains the reviewed patch plan. Save it at `/repo/retobs/integration-plan.json` before apply. Required unresolved mappings block apply, and stale precondition hashes block mutation. Apply returns every changed file and its record contains the reversal patches. Do not describe this as one-step wiring.

Verify is a measurement step. `ready` requires observed topology, candidate evidence, and telemetry health. A project with no observed traces, unavailable candidate mapping, or telemetry loss is not ready even if apply changed files.

CLI uses the same inputs:

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --plan retobs/integration-plan.json
```

After readiness, use `evaluate`, `compare`, `inspect_query`, and `get_report` for explicit retrieval evidence.
