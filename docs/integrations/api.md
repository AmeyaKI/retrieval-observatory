# Local API

`retobs serve --db .retobs/results.db` serves the local dashboard and API on `127.0.0.1` by default. It is unauthenticated; do not expose it to an untrusted network.

Use `GET /dbs` to select a database, then scope reads to `/dbs/{db_id}/...`. Run and query evidence must retain explicit database and Run scope.

`GET /config/schema` describes advanced evaluation configuration and `POST /config/validate` validates it without running. The API accepts declarative configuration, not arbitrary live Python objects. For project instrumentation, use the reviewed `integrate_project` MCP workflow or its CLI equivalent.

Responses expose unavailable evidence and instrumentation-health limits explicitly. See [MCP](mcp.md) and [privacy](../PRIVACY.md).
