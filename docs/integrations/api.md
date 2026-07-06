# REST API — trigger runs & read results

retobs ships a FastAPI app (`retobs serve`) that, alongside the dashboard's read endpoints, can
**trigger benchmark runs from a config** and return **diagram-ready JSON**. Pipelines are
expressed as configuration (adapter specs), not live Python objects, so they travel over the wire.

Start the server:

```bash
retobs serve --db .retobs/results.db          # http://localhost:4000
```

`{db_id}` is the slug of the loaded database (see `GET /dbs`); with one db it is the file stem.

## Discover the config shape

`GET /config/schema` → the `ExperimentConfig` JSON schema, a runnable `example_config`, and
per-adapter / per-dataset snippets. `POST /config/validate` with `{"config": {...}}` dry-run
validates a config (no run) → `{valid, status, items}`. Use these to build and check a config
before triggering a run.

## Trigger a run

`POST /dbs/{db_id}/runs`

```jsonc
{
  "config": {                                  // an ExperimentConfig
    "experiment": {"name": "bm25-baseline"},
    "dataset": {"type": "custom", "name": "custom",
                "queries_path": "q.jsonl", "corpus_path": "c.jsonl"},
    "pipelines": [{"id": "bm25", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}]
  },
  "wait": true,          // optional; omit for a background job
  "max_queries": 20      // optional cap (recommended with wait=true)
}
```

- **Background (default):** returns `{"run_id": "...", "status": "running"}`. Poll status, then
  read the existing metric endpoints.
- **`wait=true`:** runs bounded-synchronously and returns `{"run_id", "status": "completed", "metrics": {...}}`.

`GET /dbs/{db_id}/runs/{run_id}/status` → `{"run_id", "status": "running|completed|error", "error"}`.

## Compare two configs

`POST /dbs/{db_id}/compare-configs`

```jsonc
{"baseline_config": { ... }, "candidate_config": { ... }, "max_queries": 20}
```

Runs both and returns `{"baseline_run_id", "candidate_run_id", "comparison": [...], "significant": bool}`
(paired bootstrap test per metric).

## Diagram-ready JSON

`GET /dbs/{db_id}/runs/{run_id}/diagram` → per-pipeline `nodes` (each stage's Recall/NDCG@10/latency
as `{mean, ci_low, ci_high}`) and `edges` (linear + fused arms), plus `operator_dag` when V2 traces
exist. This is what `retobs diagram` renders to HTML (see [mcp.md](mcp.md) for the agent tool).

## Reading results (existing endpoints)

- `GET /dbs/{db_id}/runs/{run_id}/metrics` — aggregated metrics + CIs
- `GET /dbs/{db_id}/runs/{run_id}/pareto-frontier` — Pareto-optimal pipelines
- `GET /dbs/{db_id}/runs/{run_id}/overview` — headline winner, topology, diagnostics
- `GET /dbs/{db_id}/runs/{run_id}/operator-attribution` — per-operator marginal contribution

## Auth & rate limiting

Local-first, so auth is **off by default**. Set `RETOBS_API_TOKEN` to require
`Authorization: Bearer <token>` on the run-trigger endpoints (reads stay open). The number of
concurrently executing runs is capped by `RETOBS_MAX_CONCURRENT_RUNS` (default 2); exceeding it
returns `429`. Multi-tenant hosting is out of scope.
