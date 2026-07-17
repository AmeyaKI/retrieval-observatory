# Data and privacy

retobs is local-first, but local storage is still sensitive storage. Queries, candidates, metadata, labels, and traces may contain customer, personal, or proprietary data.

- The dashboard binds to `127.0.0.1` by default and is unauthenticated.
- Telemetry queue capacity, overflow policy, sampling, and retry behavior are explicit configuration.
- Instrumentation health makes sampling, drops, serialization failures, and export failures visible.
- Redaction runs before enqueue and persistence according to the integration manifest.

Before production use, choose retention and sampling deliberately, restrict database/filesystem access, review report artifacts before upload, and place the dashboard behind trusted controls if loopback is insufficient. External label or generation providers receive the supplied content under their own policies.

Report vulnerabilities through [SECURITY.md](../SECURITY.md).
