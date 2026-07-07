# Agent quickstart — retobs MCP

Two copy-paste journeys. Tool names match the MCP server (`retobs mcp`).

Register MCP in your agent (Claude Code, Cursor, Codex):

```json
{ "mcpServers": { "retobs": { "command": "retobs", "args": ["mcp"] } } }
```

Bootstrap: `pip install 'retrieval-observatory[mcp]'` · `retobs mcp init` · `retobs doctor`

## Journey A — Benchmark a config

1. **`describe_config`** — returns JSON schema + example config. No run.
2. **`validate_config`** — pass your config dict. Fix errors before running.
3. **`benchmark_config`** — pass validated config + `max_queries: 50` for a bounded run.
   - For YAML on disk in an external project: **`benchmark_config_file(config_path=...)`**
   - Pass **`config_base_dir`** when using relative dataset paths or `adapter.import` factories.
   - Also accepts the legacy descriptor shape `{name, dataset, pipelines}` (normalized internally).
4. **`get_run_metrics`** — aggregated metrics with bootstrap CIs.
5. **`get_pareto_frontier`** — end-to-end latency vs NDCG@10; CIs included.
6. **`get_pipeline_graph`** — canonical DAG graph (preferred) or **`get_pipeline_diagram`** for legacy per-stage view.

**Expected:** step 3 returns `{run_id, metrics, headline_winner}`; step 6 shows fan-in edges into merge nodes for hybrid configs.

## Journey B — Instrument existing code

1. **`bootstrap_project`** (optional) — scaffolds `retobs/config.yaml`, `retobs-mcp.yaml`, and stubs in your project root.
2. **`describe_integration`** — optional `framework`: `python` | `langchain` | `llamaindex` | `fastapi` | `http`.
3. Wire the returned snippet into your service (or use `adapter.http` for zero-code HTTP benchmark).
4. **`push_traces`** — ingest V2 trace dicts into a benchmark run, or run a smoke benchmark.
5. **`verify_integration`** — reports trace count, stages seen, instrumentation mode, dashboard deep link, and suggested next tools. Pass `expected_stages` to check wiring.
6. **`get_run_metrics`** / open dashboard at the returned URL (`retobs serve` defaults to port 4000).

**CLI twins:** `retobs integrate --framework langchain --check` · `retobs doctor`

## Example transcript (FiQA hybrid demo)

```text
> validate_config(examples/advanced/hybrid_fiqa_demo/config_fiqa.yaml as JSON)
{ "valid": true, ... }

> benchmark_config_file(config_path="examples/advanced/hybrid_fiqa_demo/config_fiqa.yaml", max_queries=20)
{ "run_id": "a1b2c3d4", "headline_winner": { ... } }

> verify_integration(run_id="a1b2c3d4")
{ "trace_count": 0, "instrumentation": "benchmark_only", "pipeline_ids": ["bm25_only", "dense_only", "hybrid", "hybrid__rerank"], "next": ["get_run_metrics", "get_pareto_frontier", "get_pipeline_graph"] }

> get_pipeline_graph(run_id="a1b2c3d4")
{ "pipelines": [{ "nodes": [...], "edges": [...] }] }
```

Trace-native runs: `trace_count > 0`, `instrumentation: "trace_native"`, and `stages_seen` lists operator op_ids from V2 spans.

## Custom Python in an external folder

```text
> bootstrap_project(project_root="/path/to/my-rag", framework="python")
{ "config_path": "/path/to/my-rag/retobs/config.yaml", "files_written": [...], "next": [...] }

> benchmark_config_file(config_path="/path/to/my-rag/retobs/config.yaml", max_queries=10)
{ "run_id": "...", "metrics": {...} }
```

Add `queries.jsonl`, `corpus.jsonl`, and `qrels.jsonl` under `retobs/`, or switch the dataset stanza to `beir/nfcorpus`.
