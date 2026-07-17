# Start

Install the dashboard and MCP extras:

```bash
pip install "retrieval-observatory[dashboard,mcp]"
```

For an existing retrieval project, use the reviewed integration sequence:

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --plan retobs/integration-plan.json
```

`plan` detects supported mappings and emits exact precondition hashes. `apply` rejects unresolved mappings or stale hashes and returns the changed files. `verify` is evidence-based: it is not `ready` until observed topology, candidate evidence, and telemetry health satisfy the declared capability checks.

Evaluate a callable with explicit inputs:

```bash
retobs evaluate mypackage.search:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl
retobs serve --db .retobs/results.db
```

The dashboard is loopback-only by default. Continue with the [workflow](WORKFLOW.md) and [integration support matrix](INTEGRATIONS.md).
