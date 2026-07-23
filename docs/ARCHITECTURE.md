# Architecture

retobs is a local-first evidence-control plane for multi-stage retrieval pipelines. CLI, SDK, MCP, dashboard, and CI share one evidence path. When identity, topology, candidates, labels, lineage, or telemetry are missing, retobs reports that limit instead of inventing a conclusion.

## Evidence path

```text
integrate plan → reviewed apply → verify (optional release policy)
evaluate callable/config ──┐
push_traces (production) ──┼→ scoped store (SQLite | PostgreSQL)
testsets generate ─────────┘
        ↓
compare + local release policy → PASS | HOLD | BLOCK | FAIL
        ↓
inspect-query / Candidate Lineage Explorer → passport → optional recorded replay
        ↓
validate: smallest fix → same Test Set → compare again
```

The dashboard reads store projections only. It does not invent topology, candidate movement, release status, or causal explanations.

## Subsystems

| Area | Role |
|---|---|
| `integrations/` | Detect → plan → apply reviewed patches → verify observed topology, candidates, and telemetry health. |
| `runner/` + `pipeline/` | Evaluate callables or YAML configs into Runs with operator DAG traces, metrics, and diagnostics. |
| `metrics/` | Aggregate metrics, paired comparison validity, intervals, corrections, and declared-slice evaluation. |
| `release/` | Load versioned local policies; assess claim-scoped readiness; emit one canonical release decision. |
| `store/` | One SQLite/PostgreSQL contract for runs, traces, metrics, diagnostics, production services, and instrumentation health. |
| `tracing/` | Unified `RetrievalTrace`, buffered export, candidate lineage, lineage diffs, and instrumentation health. |
| `evidence/` | Scoped query-evidence documents for CLI, SDK, MCP, and dashboard. |
| `diagnostics/` | Rule engine over recorded traces; findings surface inside Runs, Compare, and Queries. |
| `forge/` via `testsets` | Corpus stress-test generation; public CLI is `retobs testsets`. |
| `sdk/`, `mcp/`, `cli.py`, `dashboard/` | Task-parity surfaces gated by `contracts/public_surface.json`. |

## Public task surface

Supported commands and tools are release-gated: `integrate`, `evaluate`, `compare`, `inspect-query`, `report`, `serve`, `production`, `testsets`, and `demo`, plus the matching SDK/MCP exports. Dashboard modes are Home, Runs, Compare, Queries, Production, and Test Sets.

## Release and lineage contracts

- A local YAML policy names exact metric keys, budgets, minimum paired `n`, and exact declared slices. Its digest is embedded in the release artifact.
- Decision statuses: `PASS` (bounded non-inferiority), `HOLD` (valid but inconclusive), `BLOCK` (missing/invalid required evidence), `FAIL` (proven policy-critical regression).
- Claim scopes stay separate: promotion, aggregate/slice evaluation, lineage diagnosis, lineage diff, and production traces. Lineage blocks promotion only when the policy requires it.
- Candidate lineage is derived from recorded transitions: routes, operational outcomes, passports, and baseline/candidate diffs when query, document revision, and topology evidence align.

See [retrieval release decisions](guides/retrieval-release-decisions.md), [Candidate Lineage Explorer](guides/candidate-lineage-explorer.md), and [evidence and trust](EVIDENCE_AND_TRUST.md).

## Production safety boundary

- `retobs serve` binds to `127.0.0.1` by default; the dashboard is unauthenticated and local-first.
- Telemetry queue capacity, overflow policy, sampling, and retry limits are explicit configuration.
- Instrumentation health exposes sampling, drops, serialization failures, and export failures.
- Queries, candidates, metadata, labels, and traces may be sensitive.
- Redaction runs before enqueue and persistence according to the integration manifest.

Deploy behind trusted authentication and network controls if loopback-only access is not sufficient.
