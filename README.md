# retrieval-observatory (retobs)

[PyPI version](https://pypi.org/project/retrieval-observatory/)

Most RAG evaluation tools score end-to-end answer quality and stop there. They don't tell you **which stage helped**, **what it cost in latency**, or **which queries will fail before you run retrieval**. retobs is an open-source multi-stage retrieval benchmark and local dashboard that measures per-stage contribution, failure diagnosis, latency–quality tradeoffs, and query difficulty — so you can decide whether to add that reranker (or switch to dense) with evidence, not intuition.

**Headline result:** On BEIR/FiQA, dense retrieval (`all-MiniLM-L6-v2`) outperforms BM25 by **+132% NDCG@10** (0.369 vs 0.159) at **~130× lower latency** than cross-encoder reranking. On SciFact and FiQA, dense-only is the **sole Pareto-optimal** pipeline. On NFCorpus, dense/rerank/RRF NDCG CIs overlap — no single winner on quality alone.

Quality–Latency Tradeoff — NFCorpus Pareto frontier



---

## Install

```bash
pip install "retrieval-observatory[demo,dashboard,dense]"
```

For development from source:

```bash
git clone https://github.com/AmeyaKI/retrieval-observatory.git && cd retrieval-observatory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[demo,dashboard,dense]"
```

---

## Quickstart (~5 minutes)

Run BM25 on 50 SciFact queries, then open the dashboard.

**PyPI install** (bundled example config):

```bash
CFG="$(python -c 'from retrieval_observatory import EXAMPLES_DIR; print(EXAMPLES_DIR / "quickstart_scifact.yaml")')"
retobs validate --config "$CFG"
retobs run --config "$CFG"
retobs serve --db .retobs/quickstart_scifact.db
```

**From a git clone** (repo `examples/` tree):

```bash
retobs validate --config examples/quickstart_scifact.yaml
retobs run --config examples/quickstart_scifact.yaml
retobs serve --db .retobs/quickstart_scifact.db
```

Open `http://localhost:8000` — explore metrics, latency, and query-level diagnostics.

### Full examples and BEIR publish configs

The PyPI wheel includes quickstart YAMLs only. For the full `examples/` demos (HTTP quickstart, temporal demo, dashboard demo with JSONL data) and multi-dataset BEIR sweeps, clone the repo:

```bash
git clone https://github.com/AmeyaKI/retrieval-observatory.git
cd retrieval-observatory
./scripts/run_beir_publish.sh full-sweep   # uses configs/beir_publish/
```

---

## Benchmark Results

Cross-dataset summary (full BEIR test splits, 4 independent pipelines). See [results/BENCHMARK_ANALYSIS.md](results/BENCHMARK_ANALYSIS.md) for motivation, Pareto analysis, classifier calibration, and limitations.


| Dataset         | bm25 NDCG@10 | dense_only | rrf_hybrid | bm25__rerank | Pareto optimal   |
| --------------- | ------------ | ---------- | ---------- | ------------ | ---------------- |
| NFCorpus (323q) | 0.264        | **0.310**  | 0.304      | 0.310        | bm25, dense_only |
| SciFact (300q)  | 0.544        | **0.640**  | 0.623      | 0.628        | dense_only       |
| FiQA (648q)     | 0.159        | **0.369**  | 0.290      | 0.260        | dense_only       |


Four pipelines: `bm25`, `dense_only`, `rrf_hybrid`, `bm25__rerank`. Stage attribution uses the bm25 → bm25__rerank prefix pair only. JSON exports and regeneration: [results/RESULTS_OVERVIEW.md](results/RESULTS_OVERVIEW.md).

---

## What retobs tells you

```
Stage Contribution: bm25 → bm25__rerank
┌───────────────┬──────────┬──────────┬──────────────┬────────────────┐
│ Metric        │ Before   │ After    │ Δ            │ Significant?   │
├───────────────┼──────────┼──────────┼──────────────┼────────────────┤
│ recall@10     │ 0.1190   │ 0.1380   │ +0.0190 (+16%)│ q=0.041 ✓    │
│ ndcg@10       │ 0.2640   │ 0.3100   │ +0.0460 (+17%)│ q=0.012 ✓    │
│ Latency P50   │ 2ms      │ 4,057ms  │ +4,055ms     │ —             │
└───────────────┴──────────┴──────────┴──────────────┴────────────────┘
```

1. **Stage attribution** — What did each stage add in quality, cost, and latency? BH-corrected significance on paired queries.
2. **Failure diagnosis** — Candidate misses, lexical mismatches, reranker drops — labeled per query.
3. **Latency–quality tradeoff** — Pareto frontier and budget slider; see whether reranking is worth it at your latency budget.

Core promise:

- Comparable **Recall@K, NDCG@K, MRR, MAP, latency percentiles, and estimated cost per 1k queries** across pipelines.
- Multi-stage pipelines with independent stage analysis and temporal recall for time-sensitive datasets.

---

## How It's Different


| Tool            | What it measures                                                                   |
| --------------- | ---------------------------------------------------------------------------------- |
| BEIR            | End-to-end pipeline accuracy on fixed datasets                                     |
| RAGAs / TruLens | Answer quality given retrieved context                                             |
| **retobs**      | **Per-stage contribution: what did each stage add in quality, cost, and latency?** |


retobs is not a leaderboard and not an answer evaluator. It's a diagnostic layer between "I have a retrieval pipeline" and "I understand how to improve it."

---

## Install (development)

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

## Stage Attribution in 60 Seconds

Add `ablations: true` to your combinations config and retobs automatically runs the prefix pipeline too:

```yaml
stages:
  bm25:
    type: adapter.bm25
    config: {k: 100}
  rerank:
    type: adapter.hf_crossencoder
    config:
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      k: 10

combinations:
  include:
    - [bm25, rerank]
  ablations: true   # automatically also runs [bm25] alone — no extra config needed
```

`retobs run` then prints the stage contribution table showing exactly what the reranker added.

For a 3-stage pipeline, `ablations: true` generates **all valid ordered subsequences** — not just prefixes:

```yaml
combinations:
  include:
    - [bm25, fast_rerank, precise_rerank]
  ablations: true
# Generates: bm25 | bm25__fast_rerank | bm25__precise_rerank | bm25__fast_rerank__precise_rerank
# Answers: does skipping fast_rerank and going direct to precise_rerank beat the cascade?
```

To test only whether a specific stage pays for itself, name it explicitly:

```yaml
combinations:
  include:
    - [bm25, fast_rerank, precise_rerank]
  ablations: [fast_rerank]   # generates only: without fast_rerank vs with fast_rerank
```

Optionally set a latency budget to get a one-line verdict in CI:

```bash
retobs run --config my_experiment.yaml --latency-budget-ms 1000
```

---

## Query Difficulty Classifier

Predict whether a query will be hard for retrieval **before** running your pipeline, using only query text. Labels come from post-hoc diagnostics (mean Recall across pipelines on a specific corpus), so models are **dataset-specific**.

```bash
# Install classifier dependencies
pip install -e ".[classifier]"

# After one or more benchmark runs on the same dataset:
retobs classifier train --dataset beir/nfcorpus

# Inspect cross-val accuracy, Brier score, and feature importances:
retobs classifier report --dataset beir/nfcorpus

# Score a single query:
retobs classifier predict --model .retobs/models/query_difficulty_beir_nfcorpus.joblib \
  --query "What mitochondrial mechanisms were studied since 2019?"

# Next benchmark run auto-applies predictions when a matching model exists
retobs run --config my_experiment.yaml
```

The dashboard shows **Classifier Calibration**: mean Recall@10 (with bootstrap CIs) grouped by predicted difficulty. If predicted-hard queries have lower Recall@10 than predicted-easy ones, the classifier is doing useful work.

**Caveat:** The classifier predicts observatory difficulty under *your* pipelines on *your* corpus—not intrinsic question hardness. Train and evaluate on the same dataset; cross-dataset use is unsupported.

---

## HTTP Quickstart

If your retrieval service is already running, point retobs at it and get metrics immediately:

```bash
# Start the mock server
pip install fastapi uvicorn rank-bm25
uvicorn examples.http_quickstart.server:app --port 8000

# Benchmark it
retobs run --config examples/http_quickstart/config.yaml
```

The HTTP adapter POSTs `{"query": str, "k": int}` and expects `{"results": [{"id", "text", "score"}]}`.

---

## Quick Test Of The Observatory

```bash
# 1. Install/update editable package
source .venv/bin/activate
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"

# 2. Confirm CLI commands are registered
retobs --help

# 3. Generate a starter experiment config
retobs init --mode bm25+reranker --output my_experiment.yaml

# 4. Validate before running
retobs validate --config my_experiment.yaml

# 5. Run the benchmark (stage attribution table printed automatically)
retobs run --config my_experiment.yaml --no-cache

# 6. Open the interactive dashboard
retobs serve --db .retobs/results.db --port 8000
```

Open `http://localhost:8000` — move the latency budget slider and watch the stage verdict update live.

Load multiple result databases in one dashboard (sidebar tabs per DB):

```bash
retobs serve --db .retobs/publish_smoke_scifact.db --db .retobs/dashboard_demo.db
# or comma-separated:
retobs serve --db .retobs/a.db,.retobs/b.db
# or env var (colon-separated):
RETOBS_DASHBOARD_DBS=.retobs/a.db:.retobs/b.db retobs serve
```

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
    - [bm25, rerank]
    - [dense, rerank]
  ablations: true   # auto-generates [bm25] and [dense] prefix pipelines

metrics:
  recall_at_k: [1, 5, 10, 20]
  precision_at_k: [5, 10]
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

Cost is configured for relative tradeoff analysis:

```yaml
costs:
  bm25:
    per_1k_queries: 0.10
  rerank:
    per_1k_queries: 1.50
```

`retobs run` and the dashboard both treat this as an **estimated** cost model from your YAML, not measured cloud billing telemetry.

> **Stage cache note:** When `execution.cache_results: true`, retrieval stages are cached by
> `hash(stage_config + upstream_candidates + query_id)`. The upstream candidate fingerprint ensures
> that two pipelines sharing the same reranker but with different first-stage retrievers (e.g.
> `bm25→rerank` vs `dense→rerank`) never share reranker snapshots. Stage 0 (first retriever) still
> shares cache entries across ablation combos as intended. Use `--no-cache` when you want
> fully independent execution for reproducibility auditing.

### HTTP adapter schema

The `adapter.http` stage wraps any REST endpoint. Your server must accept:

**Request** — `POST` with JSON body:

```json
{"query": "user question text", "k": 100}
```

When query filters are set, a `filters` object is also included.

**Response** — JSON in either shape:

```json
{"documents": [{"id": "doc_1", "text": "...", "score": 0.92}]}
```

```json
[{"id": "doc_1", "text": "...", "score": 0.92}]
```

Each document object must include the configured ID field (default `id`). Text and score fields default to `text` and `score` but can be remapped:

```yaml
- type: adapter.http
  url: http://localhost:8080/retrieve
  config:
    k: 100
    id_field: doc_id
    text_field: content
    score_field: relevance
```

See `[examples/http_quickstart/server.py](examples/http_quickstart/server.py)` for a reference implementation.

### Custom Python retriever via `adapter.import`

Use `adapter.import` to load a Python factory callable from your own module without editing retobs internals:

```yaml
- type: adapter.import
  retriever_id: keyword
  config:
    factory: retriever:build_retriever
    k: 10
```

Supported factory paths:

- `package.module:callable`
- `package.module.callable`

Factory signature:

```python
def build_retriever(corpus: dict | None, stage_cfg: dict, **kwargs):
    ...
    return retriever_or_reranker, k
```

Runnable example: `[examples/custom_retriever/](examples/custom_retriever/)`

---

## Custom Dataset Format

### `queries.jsonl`

```json
{"query_id":"q1","text":"What changed in the refund policy?","relevant_doc_ids":{"doc_17":2,"doc_22":1},"temporal_anchor":"2024-01-15T00:00:00"}
```

`relevant_doc_ids` can be a list for binary labels or a dict for graded relevance.

### `corpus.jsonl`

```json
{"id":"doc_17","title":"Refund policy update","text":"Refunds are now processed within 7 days.","timestamp":"2024-01-10T00:00:00"}
```

### Optional `qrels.jsonl`

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

---

## Dashboard Features


| Feature                  | Description                                                                               |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| Stage Attribution        | Before/after metric table for each pipeline pair with BH-corrected significance.          |
| Tradeoff Explorer        | Latency budget + min quality delta sliders; verdict computed client-side.                 |
| Experiment Overview      | Headline winner, difficulty buckets, failure-label summary, reproducibility warnings.     |
| Pipeline Architecture    | Stage-by-stage flow diagram with per-stage quality and latency.                           |
| Stage Combination Matrix | Compact view of quality, latency, and optional cost-per-1k by pipeline/stage.             |
| Query Explorer           | Query-level diagnostics with failure labels, missing relevant IDs, and difficulty bucket. |
| Run Comparison           | Side-by-side metrics with query-ID-aligned paired bootstrap p-values.                     |
| Recall@K Curves          | Recall trends across K with BEIR reference lines when available.                          |
| Stage Recall Funnel      | Shows how much candidate recall survives through reranking stages.                        |
| Latency Breakdown        | P50/P95/P99 plus profiling metrics for compute, network, and retries.                     |
| Segment Analysis         | NDCG@10 by query metadata such as number of relevant docs.                                |


---

## Example Runs

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

### Temporal Recall Demo

```bash
pip install -e ".[demo,dashboard]"
python examples/temporal_demo/generate_data.py
retobs run --config examples/temporal_demo/config.yaml --no-cache
retobs serve --db .retobs/temporal_demo.db
```

This demo intentionally includes old and new relevant documents per query so `recall@1` and `temporal_recall@1` diverge when top-ranked hits are stale.

### RRF Hybrid (BM25 + Dense)

```bash
pip install -e ".[demo,dashboard,dense]"
retobs run --config examples/rrf_hybrid.yaml
```

### Dense vs BM25+Cohere Hybrid

```bash
pip install -e ".[demo,dashboard,dense,cohere]"
export COHERE_API_KEY=your-key-here
retobs run --config examples/hybrid_comparison.yaml
```

---

## CLI Reference

```bash
retobs init      --mode MODE --output PATH                Generate starter config and sample data
retobs validate  --config PATH [--db PATH]                Validate config and dataset before running
retobs run       --config PATH [--no-cache]               Run a benchmark experiment
                             [--latency-budget-ms N]      Print verdict against stage latency delta
retobs serve     --db PATH [--db PATH ...] [--port N]      Start dashboard (repeat --db for multiple SQLite files)
retobs compare   RUN_ID_1 RUN_ID_2 --db PATH              Compare runs with paired bootstrap tests
retobs inspect   RUN_ID --query QUERY_ID [--pipeline ID]  Debug per-query retrieval results
```

Init modes: `beir`, `custom-jsonl`, `http-endpoint`, `bm25+dense` (includes RRF), `bm25+reranker` (includes ablations).

---

## Run The Test Suite

```bash
source .venv/bin/activate
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"
pytest tests/ -q
npm --prefix retrieval_observatory/dashboard/ui run build
python -m compileall retrieval_observatory -q
```

---

## Dashboard Development

The dashboard UI is **pre-built in the PyPI wheel**, so `retobs serve` works after `pip install` with no Node.js required. When developing from a git clone and editing React sources, rebuild the UI:

```bash
cd retrieval_observatory/dashboard/ui
npm install
npm run dev      # hot-reloading dev server on :5173 (proxies API to retobs serve)
npm run build    # rebuild dist/ before python -m build or tagging a release
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
| `langchain`  | langchain-core                          | LangChain adapter (programmatic use)                         |
| `llamaindex` | llama-index-core                        | LlamaIndex adapter (programmatic use)                        |
| `pgvector`   | asyncpg, pgvector                       | Pgvector adapter                                             |
| `llm-judge`  | google-generativeai, anthropic, openai  | LLM-assisted relevance judging                               |


PostgreSQL backend (`asyncpg`) is community-supported and not CI-tested. SQLite is recommended for evaluation workloads.

```bash
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"
```

