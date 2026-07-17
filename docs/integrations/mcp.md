# MCP

Install and register the MCP server:

```bash
pip install "retrieval-observatory[mcp]"
```

```json
{
  "mcpServers": {
    "retobs": { "command": "retobs", "args": ["mcp"] }
  }
}
```

Use `integrate_project` for the reviewed plan/apply/verify sequence. It accepts `project_root`, `phase`, an optional reviewed `plan`, or `plan_path` for the saved plan. See [AGENT_QUICKSTART.md](AGENT_QUICKSTART.md).

The release-gated tool inventory is `evaluate`, `evaluate_file`, `compare`, `inspect_query`, `get_report`, `describe_config`, `validate_config`, `integrate_project`, `verify_integration`, `push_traces`, and `get_pipeline_graph`.

MCP results preserve evidence limits: a missing candidate transition, unsupported integration mapping, or failed exporter stays unavailable or failed rather than becoming a quality claim.
