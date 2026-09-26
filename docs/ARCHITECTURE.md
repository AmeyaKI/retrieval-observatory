# Architecture

retobs is a local-first evidence layer for multi-stage retrieval pipelines. The CLI, SDK, MCP
server, dashboard, and CI read the same stored evidence. When identity, topology, candidates,
judgments, or capture are missing, retobs reports that limit instead of inventing a conclusion.

## Evidence path

```text
Connect:     integrate plan → review → re-plan → apply → scenarios → verify (8 capabilities) → revert
Evaluate:    evaluate callable/config → Run (manifest, metrics, one trace per query and pipeline)
             → journey projection → investigation rows (SQLite | PostgreSQL, schema v3)
Investigate: Run → query → candidates → one document's journey → loss boundary
Audit:       compare BASELINE CANDIDATE --policy (v3) → audit-1 → PASS | HOLD | BLOCK | FAIL
             → changed queries → Investigate compare=BASELINE
```

The dashboard reads stored projections through the same service as the CLI and MCP. It does not
compute topology, candidate movement, or release status in the browser.

## Subsystems

| Area | Role |
|---|---|
| `integrations/` | Detect, plan, apply reviewed patches, verify eight capabilities from observed traces, revert, and persist the integration record Connect reads. |
| `sdk/`, `tracing/` | `@observe` / `@trace_scope` capture of each operator's actual boundary, framework callbacks, `RetrievalTrace`, buffered export, instrumentation health. |
| `runner/`, `pipeline/` | Evaluate callables or YAML configs into Runs; build the investigation projection when a Run finishes. |
| `datasets/` | Queries, corpora, namespaced judgments, chunk maps, evaluation specs, dataset fingerprints. |
| `evidence/` | Journey projection and the one investigation service behind every transport (`inspect_query`, `inspect_document`, run comparison). |
| `metrics/` | Per-query and aggregate metrics, paired statistics. |
| `release/` | Policy loading (v2 and v3), selector resolution, compatibility assessment, check evaluation, and the `audit-1` release audit. |
| `store/` | One SQLite/PostgreSQL contract for Runs, traces, metrics, investigation rows, integration records, and instrumentation health; additive migrations. |
| `cli.py`, `mcp/`, `dashboard/` | Transports over the same services, gated by `contracts/public_surface.json`. |

## Public task surface

CLI commands: `integrate`, `evaluate`, `report`, `compare`, `inspect-query`, `inspect-document`,
`storage`, `serve`, `mcp`, and `demo`. The dashboard has three workflows, Investigate, Connect,
and Audit, plus Help. The SDK and MCP expose the same tasks; see [reference](REFERENCE.md).
Features retired in 0.7.0 answer HTTP 410 and are listed in
[migrating to focused retobs](guides/migrating-to-focused-retobs.md).

## Contracts

- A v3 policy names checks with semantic selectors (`final_retrieval`, `query`,
  `operator:<id>`), tolerances, minimum paired `n`, pair coverage, slices, and a failure-rate
  cap. Its digest is embedded in the audit.
- Claim scopes stay separate: promotion, aggregate or slice evaluation, lineage diagnosis,
  lineage diff, and production traces.
- Journeys are joined across Runs on (query, namespace, unit, entity), never on text; a corpus
  change blocks matched claims.

See [investigate your pipeline](guides/investigate-your-pipeline.md),
[retrieval release decisions](guides/retrieval-release-decisions.md), and
[evidence limitations](guides/evidence-limitations.md).

## Production safety boundary

- `retobs serve` binds to `127.0.0.1` by default; the dashboard is unauthenticated and local-first.
- Capture never changes an application's return values, order, or exceptions; capture failures
  are recorded on the trace.
- Telemetry queue capacity, overflow policy, sampling, and retry limits are explicit configuration.
- Queries, candidates, metadata, judgments, and traces may be sensitive. Redaction runs before
  enqueue and persistence according to the integration manifest.

Deploy behind trusted authentication and network controls if loopback-only access is not sufficient.
