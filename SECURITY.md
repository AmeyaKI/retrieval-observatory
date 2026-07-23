# Security policy

## Supported versions

Security fixes target the latest released minor version; this alpha project does not promise backports.

## Report a vulnerability

Do not open a public issue. Use GitHub private vulnerability reporting with the affected version, impact, reproduction, and suggested mitigation.

## Deployment boundary

- `retobs serve` binds to `127.0.0.1` by default; the dashboard is unauthenticated and local-first.
- Telemetry queue capacity and overflow policy are explicit configuration.
- Instrumentation health reports sampling, drops, serialization failures, and export failures.
- Queries, candidates, metadata, labels, and traces may be sensitive.
- Redaction occurs before enqueue and persistence according to the integration manifest.

Use trusted authentication and network controls before any non-loopback deployment. See [privacy](docs/PRIVACY.md).