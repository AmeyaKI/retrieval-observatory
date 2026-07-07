# Agent quickstart — retobs MCP

## Journey 0 — Wire retobs (one agent prompt)

**ML engineer prompt:**

> Wire retobs into this project.

**Agent does:**

1. **`wire_project(project_root=...)`** — detect framework, scaffold `retobs/`, write manifest + `RETOS.md`, return `wiring_brief`
2. Apply `wiring_brief.patches` to the listed pipeline files
3. **`wire_project(project_root=..., phase="verify")`** — confirm wiring; returns `status: ready` + post-wiring commands

Register MCP once:

```json
{ "mcpServers": { "retobs": { "command": "retobs", "args": ["mcp"] } } } }
```

Bootstrap: `pip install 'retrieval-observatory[mcp]'` · `retobs doctor`

CLI twin: `retobs wire .` then `retobs wire . --verify`

---

## After wiring — benchmark

1. **`validate_config`** — pass config dict or use on-disk YAML
2. **`benchmark_config_file(config_path="retobs/config.yaml")`** — smoke eval with sample JSONL
3. **`get_run_metrics`** / **`get_pareto_frontier`** / **`get_pipeline_graph`**

Human: `retobs run --config retobs/config.yaml` · `retobs serve --db .retobs/results.db`

---

## After wiring — trace

1. Hooks from `wiring_brief` or **`describe_integration(framework=...)`**
2. **`push_traces`** — ingest V2 traces
3. **`verify_integration(expected_stages=[...])`**

---

## Example transcript

```text
> wire_project(project_root="/path/to/my-rag")
{ "status": "setup_complete", "wiring_brief": { "patches": [...] }, "post_wiring_commands": {...} }

> wire_project(project_root="/path/to/my-rag", phase="verify")
{ "status": "ready", "commands": { "benchmark": "retobs run --config retobs/config.yaml", ... } }

> benchmark_config_file(config_path="/path/to/my-rag/retobs/config.yaml", max_queries=10)
{ "run_id": "...", "metrics": {...} }
```

See `RETOS.md` and `.retobs/manifest.yaml` in the wired project for persistent state.
