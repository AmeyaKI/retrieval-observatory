# Agent integration runbook

Register the MCP server with `retobs mcp`, then run one reviewed integration loop:

```text
integrate_project(project_root="/repo", phase="plan")
integrate_project(project_root="/repo", phase="apply", plan_path="/repo/retobs/integration-plan.json")
integrate_project(project_root="/repo", phase="verify")
```

The plan result contains the reviewed patch plan. Save it at `/repo/retobs/integration-plan.json` before apply. Required unresolved mappings block apply, and stale precondition hashes block mutation. Apply returns every changed file; the reversal patches are written to `/repo/retobs/integration.yaml`, not returned in the apply result. Re-running apply on an already-applied plan reports `already applied (manifest present)`.

Apply decorates each discovered operator with `@observe(...)` and the project's entrypoint (a FastAPI route handler, a `retrieve`/`search` function, or the terminal operator) with `@trace_scope(service_id, pipeline_id, db_path=...)`. Calling that entrypoint once starts, finishes, and persists a trace to `db_path` with no further setup; a relative `db_path` is anchored at the project root. The decorator is a no-op inside a request already traced by `instrument_fastapi` or a framework callback, and `@observe` functions called inside such a request add their spans to that trace.

Verify is a measurement step. It reads `retobs/integration.yaml` (verify without it fails with `no retobs/integration.yaml: run apply first`); `plan`/`plan_path` are optional on verify and must carry the applied plan's `plan_id`. `ready` requires, for every scenario, at least one persisted trace whose FIRED operator spans cover the expected operators, carry at least one output candidate with a `doc_id`, record a non-empty query text and positive wall-clock time, and pass the evidence checks MCP `verify_integration` applies (stable identity, valid topology, timing, candidate identity). When no trace is found the message names the `service_id`, `pipeline_id`, and database path it looked for.

CLI uses the same inputs:

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify
```

Pass `--framework` (CLI) or `framework=` (MCP) to override detection. After readiness, use `evaluate`, `compare`, `inspect_query`, and `get_report` for explicit retrieval evidence; `retobs evaluate` exits 1 when no query completed and prints the first failure's traceback tail.
