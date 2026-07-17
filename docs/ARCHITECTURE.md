# Architecture

retobs shares one evidence path across CLI, SDK, MCP, API, and dashboard:

```text
integration plan -> reviewed patch -> observed traces -> scoped store
evaluation callable/config -> Run + query evidence -> reports and dashboard
```

SQLite and PostgreSQL implement the same store contract. The dashboard reads canonical projections; it does not invent topology, candidate movement, or causal explanations.

## Production safety boundary

- `retobs serve` binds to `127.0.0.1` by default; the dashboard is unauthenticated and local-first.
- Telemetry queue capacity, overflow policy, sampling, and retry limits are explicit configuration.
- Instrumentation health exposes sampling, drops, serialization failures, and export failures.
- Queries, candidates, metadata, labels, and traces may be sensitive.
- Redaction runs before enqueue and persistence according to the integration manifest.

Deploy behind trusted authentication and network controls if loopback-only access is not sufficient.
