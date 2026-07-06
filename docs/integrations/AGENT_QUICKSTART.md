# Agent quickstart — retobs MCP

Two copy-paste journeys. Tool names match the MCP server (`retobs mcp`).

## Journey A — Benchmark a config

1. **`describe_config`** — returns JSON schema + example config. No run.
2. **`validate_config`** — pass your config dict. Fix errors before running.
3. **`benchmark_config`** — pass validated config + `max_queries: 50` for a bounded run.
   - Also accepts the legacy descriptor shape `{name, dataset, pipelines}` (normalized internally).
4. **`get_run_metrics`** — aggregated metrics with bootstrap CIs.
5. **`get_pareto_frontier`** — end-to-end latency vs NDCG@10; CIs included.
6. **`get_pipeline_diagram`** — same graph contract as the dashboard Architecture section.

**Expected:** step 3 returns `{run_id, metrics, headline_winner}`; step 6 shows fan-in edges into the FUSE node for hybrid configs.

## Journey B — Instrument existing code

1. **`describe_integration`** — optional `framework`: `python` | `langchain` | `llamaindex` | `fastapi` | `http`.
2. Wire the returned snippet into your service (or use `adapter.http` for zero-code HTTP benchmark).
3. Push traces or run a smoke benchmark.
4. **`verify_integration`** — reports trace count, stages seen, pipeline IDs, dashboard deep link, and suggested next tools.
5. **`get_run_metrics`** / open dashboard at the returned URL.

**CLI twins:** `retobs integrate --framework langchain --check` · `retobs doctor`

## Example transcript (FiQA hybrid demo)

```text
> validate_config(examples/hybrid_fiqa_demo/config_fiqa.yaml as JSON)
{ "valid": true, ... }

> benchmark_config(config, max_queries=20)
{ "run_id": "a1b2c3d4", "headline_winner": { ... } }

> verify_integration(run_id="a1b2c3d4")
{ "trace_count": 0, "pipeline_ids": ["bm25_only", "dense_only", "hybrid", "hybrid__rerank"], "next": ["get_run_metrics", "get_pareto_frontier", "get_pipeline_diagram"] }

> get_pipeline_diagram(run_id="a1b2c3d4")
{ "pipelines": [{ "nodes": [...], "edges": [...] }] }
```

Trace-native runs: `trace_count > 0` and `stages_seen` lists operator op_ids from V2 spans.
