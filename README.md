# retrieval-observatory (retobs)

Framework-agnostic benchmarking and diagnostics for hybrid, multi-stage RAG retrieval pipelines.

`retobs` lets an ML engineer describe a RAG retrieval stack in YAML, run it against BEIR or custom datasets, evaluate each stage and stage combination, and inspect quality, latency, failures, query difficulty, and reproducibility in a browser dashboard.

---

## Benchmark Results

Real numbers on BEIR/nfcorpus (323 queries, 3,633 docs). 95% CIs via paired bootstrap.


| Pipeline                                        | Recall@10                | NDCG@10                  | MRR                      | Latency P50 |
| ----------------------------------------------- | ------------------------ | ------------------------ | ------------------------ | ----------- |
| BM25-only (`rank-bm25`)                         | 0.119 [0.098, 0.141]     | 0.264 [0.233, 0.295]     | 0.468 [0.418, 0.514]     | 2 ms        |
| Dense-only (`all-MiniLM-L6-v2` + FAISS)         | **0.153 [0.129, 0.179]** | **0.310 [0.278, 0.341]** | 0.510 [0.464, 0.555]     | 539 ms*     |
| BM25 -> CrossEncoder (`ms-marco-MiniLM-L-6-v2`) | 0.138 [0.115, 0.163]     | 0.310 [0.275, 0.345]     | **0.530 [0.480, 0.581]** | 4,057 ms**  |


 Query encoding on CPU; latency drops significantly with GPU or batched encoding.  
 Scoring 100 BM25 candidates through a cross-encoder on CPU; GPU reduces this substantially.

Full data and observations: [results/nfcorpus/README.md](results/nfcorpus/README.md)

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate

# Full local development setup
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"
```

For a smaller install:

```bash
pip install -e ".[demo,dashboard]"
```

---

## Quick Test Of The Updated Observatory

These commands exercise the new config generator, validator, custom dataset loader, run manifest, query diagnostics, profiling metrics, dashboard API, and React dashboard build.

```bash
# 1. Install/update editable package
source .venv/bin/activate
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"

# 2. Confirm CLI commands are registered
retobs --help

# 3. Generate a starter custom experiment and tiny dataset
retobs init --mode custom-jsonl --output /tmp/retobs_custom.yaml --force

# 4. Validate before running
retobs validate --config /tmp/retobs_custom.yaml --db /tmp/retobs_custom.db

# 5. Run the generated benchmark
retobs run --config /tmp/retobs_custom.yaml --no-cache

# 6. Run the test suite
pytest tests/ -q

# 7. Build the dashboard frontend
cd retrieval_observatory/dashboard/ui
npm run build
cd -

# 8. Serve the dashboard for the generated run
retobs serve --db .retobs/results.db --port 8000
```

Open `http://localhost:8000`.

---

## New v0.2 Workflow

### Validate First

`retobs validate` checks the YAML, dataset files, adapter requirements, API key warnings, stage `k` values, output path, label mode, duplicate IDs, empty corpus docs, and missing custom qrels.

```bash
retobs validate --config examples/nfcorpus_three_way.yaml
```

Validation reports are also persisted to SQLite when a DB path is supplied.

### Generate A Starter Config

```bash
retobs init --mode custom-jsonl --output my_experiment.yaml
retobs init --mode beir --output beir_eval.yaml
retobs init --mode bm25+dense --output bm25_dense.yaml
retobs init --mode bm25+reranker --output bm25_reranker.yaml
retobs init --mode http-endpoint --output http_eval.yaml
```

For custom modes, `retobs init` also writes a tiny `retobs_sample_data/` directory with `queries.jsonl` and `corpus.jsonl`.

### Run And Inspect

```bash
retobs run --config my_experiment.yaml --no-cache
retobs serve --db .retobs/results.db
```

Each run now stores:

- aggregate metrics with bootstrap CIs
- per-stage raw results
- query diagnostics and failure labels
- query difficulty buckets
- profiling signals such as compute/network/retry time
- a reproducibility manifest with config hash, package versions, platform, git commit, and dataset fingerprint

---

## YAML Stage Combinations

You can define stages once and ask `retobs` to expand the exact combinations you want to benchmark.

```yaml
experiment:
  name: my-rag-sweep

dataset:
  type: custom
  name: custom
  queries_path: data/queries.jsonl
  corpus_path: data/corpus.jsonl
  timestamp_field: timestamp
  metadata_fields: [source]

stages:
  bm25:
    type: adapter.bm25
    config: {k: 100}

  dense:
    type: adapter.hf_biencoder
    config:
      model: sentence-transformers/all-MiniLM-L6-v2
      k: 100

  rerank:
    type: adapter.hf_crossencoder
    config:
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      k: 10

combinations:
  include:
    - [bm25]
    - [dense]
    - [bm25, rerank]
    - [dense, rerank]

metrics:
  recall_at_k: [1, 5, 10, 20]
  ndcg_at_k: [10]
  mrr: true
  map: true

execution:
  concurrency: 4
  timeout_seconds: 60
  cache_results: true

output:
  store: sqlite
  db_path: .retobs/results.db
```

Expanded pipeline IDs are stable, for example `bm25`, `dense`, `bm25__rerank`, and `dense__rerank`.

---

## Custom Dataset Format

### `queries.jsonl`

Each line is one query:

```json
{"query_id":"q1","text":"What changed in the refund policy?","relevant_doc_ids":{"doc_17":2,"doc_22":1},"temporal_anchor":"2024-01-15T00:00:00","tags":["policy"],"metadata":{"tenant":"acme"}}
```

`relevant_doc_ids` can be either a list for binary labels or a dictionary for graded relevance.

### `corpus.jsonl`

Each line is one document or chunk:

```json
{"id":"doc_17","title":"Refund policy update","text":"Refunds are now processed within 7 days.","timestamp":"2024-01-10T00:00:00","source":"policy_handbook","metadata":{"section":"billing"}}
```

### Optional `qrels.jsonl`

Use this when labels are easier to store separately:

```json
{"query_id":"q1","doc_id":"doc_17","grade":2}
```

`qrels.tsv` in TREC-style format is also supported.

---

## LLM-Assisted Labels

Gold labels are the default and remain the recommended evaluation source.

For unlabeled datasets, you can opt into LLM-assisted labels:

```yaml
labels:
  mode: pooled_llm_judge   # gold, llm_judge, or pooled_llm_judge
  judge: gemini            # gemini, openai, or anthropic
  model: gemini-2.0-flash
  cache_path: .retobs/llm_judge_cache.db
```

Set the matching API key before running:

```bash
export GOOGLE_API_KEY=...
# or OPENAI_API_KEY=...
# or ANTHROPIC_API_KEY=...
```

LLM-judged labels are cached and should be treated as auditable synthetic labels, not human ground truth.

---

## Dashboard Features


| Feature                  | Description                                                                               |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| Experiment Overview      | Headline winner, difficulty buckets, failure-label summary, reproducibility warnings.     |
| Pipeline Architecture    | Stage-by-stage flow diagram with per-stage quality and latency.                           |
| Stage Combination Matrix | Compact view of quality, latency, and optional cost-per-1k by pipeline/stage.             |
| Query Explorer           | Query-level diagnostics with failure labels, missing relevant IDs, and difficulty bucket. |
| Run Comparison           | Side-by-side metrics with query-ID-aligned paired bootstrap p-values.                     |
| Recall@K Curves          | Recall trends across K with BEIR reference lines when available.                          |
| Stage Recall Funnel      | Shows how much candidate recall survives through reranking stages.                        |
| Latency Breakdown        | P50/P95/P99 plus profiling metrics for compute, network, and retries.                     |
| Segment Analysis         | NDCG@10 by query metadata such as number of relevant docs.                                |
| BEIR Baselines           | Published BM25 reference values for supported BEIR datasets.                              |


---

## Existing Example Runs

### BEIR BM25 Baseline

```bash
retobs validate --config examples/beir_demo.yaml
retobs run --config examples/beir_demo.yaml
retobs serve --db .retobs/beir_demo.db
```

### Three-Way nfcorpus Comparison

```bash
pip install -e ".[demo,dashboard,dense]"
retobs validate --config examples/nfcorpus_three_way.yaml
retobs run --config examples/nfcorpus_three_way.yaml --no-cache
retobs serve --db .retobs/nfcorpus_three_way.db
```

### Dense vs BM25+Cohere Hybrid

```bash
pip install -e ".[demo,dashboard,dense,cohere]"
export COHERE_API_KEY=your-key-here
retobs validate --config examples/hybrid_comparison.yaml
retobs run --config examples/hybrid_comparison.yaml
retobs serve --db .retobs/hybrid_comparison.db
```

---

## CLI Reference

```bash
retobs init      --mode MODE --output PATH       Generate starter config and sample data
retobs validate  --config PATH [--db PATH]       Validate config and dataset before running
retobs run       --config PATH [--no-cache]      Run a benchmark experiment
retobs serve     --db PATH [--port N]            Start dashboard
retobs compare   RUN_ID_1 RUN_ID_2 --db PATH     Compare runs with paired bootstrap tests
```

---

## API Highlights

The dashboard backend exposes:

```text
GET  /runs
GET  /runs/{run_id}/metrics
GET  /runs/{run_id}/overview
GET  /runs/{run_id}/manifest
GET  /runs/{run_id}/diagnostics
GET  /runs/{run_id}/queries/{query_id}
GET  /runs/{run_id}/stage-matrix
POST /compare
POST /validate
POST /experiments/prepare
```

Upload endpoints require `python-multipart`, included in the `dashboard` extra.

---

## Run The Test Suite

```bash
source .venv/bin/activate
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"
pytest tests/ -q
npm --prefix retrieval_observatory/dashboard/ui run build
python -m compileall retrieval_observatory -q
```

Current expected result: `59 passed, 1 skipped`.

---

## Dashboard Development

The dashboard frontend is pre-built (`dist/` is checked in), so `retobs serve` works without any Node setup. To modify the React UI:

```bash
cd retrieval_observatory/dashboard/ui
npm install
npm run dev      # hot-reloading dev server on :5173 (proxies API to retobs serve)
npm run build    # rebuild dist/ (commit the output)
```

Or use `make dashboard-dev` / `make dashboard-build` from the repo root.

---

## Optional Dependency Groups


| Group        | Installs                                | Use for                                                      |
| ------------ | --------------------------------------- | ------------------------------------------------------------ |
| `demo`       | beir, datasets, rank-bm25               | Running BEIR datasets with BM25                              |
| `dashboard`  | fastapi, uvicorn, python-multipart      | Serving the dashboard and accepting uploads                  |
| `dense`      | sentence-transformers, faiss-cpu, torch | Dense bi-encoder retrieval and local cross-encoder reranking |
| `dev`        | pytest, pytest-asyncio, coverage, respx | Running tests                                                |
| `cohere`     | cohere                                  | Cohere reranking                                             |
| `langchain`  | langchain-core                          | LangChain adapter                                            |
| `llamaindex` | llama-index-core                        | LlamaIndex adapter                                           |
| `pgvector`   | asyncpg, pgvector                       | Pgvector adapter                                             |
| `postgres`   | asyncpg                                 | Postgres result store                                        |
| `llm-judge`  | google-generativeai, anthropic, openai  | LLM-assisted relevance judging                               |


Install multiple groups:

```bash
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"
```

