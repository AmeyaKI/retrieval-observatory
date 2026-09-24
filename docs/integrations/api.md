# Local API

`retobs serve --db .retobs/results.db` serves the local dashboard and API on `127.0.0.1` by default. It is unauthenticated; do not expose it to an untrusted network.

Use `GET /dbs` to select a database, then scope reads to `/dbs/{db_id}/...`. Run and query evidence keeps explicit database and Run scope.

| Task | Routes |
|---|---|
| Investigate | `GET /dbs/{db}/investigation/runs/{run}/queries[/{query}]`, `.../documents[/{entity}]`, `.../compare?against=BASELINE[&query=]`; `POST .../projection` builds a Run's rows explicitly. GET never writes. |
| Connect | `GET /dbs/{db}/integrations`, `GET /dbs/{db}/integrations/{service}:{pipeline}` (the record `integrate --phase verify` persisted). |
| Audit | `POST /compare` with baseline and candidate selections; the response carries the `audit-1` release audit under `audit`. |

Routes for features retired in 0.7.0 answer `410` with `{"code": "retired", "replacement": ...}`; see [migrating to focused retobs](../guides/migrating-to-focused-retobs.md#http-routes).

`GET /config/schema` describes advanced evaluation configuration and `POST /config/validate` validates it without running. The API accepts declarative configuration, not arbitrary live Python objects. For project instrumentation, use the reviewed `integrate_project` MCP workflow or its CLI equivalent.

Responses expose unavailable evidence and instrumentation-health limits explicitly. See [MCP](mcp.md) and [privacy](../PRIVACY.md).
