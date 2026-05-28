# retrieval-observatory (retobs)

**Should you add that reranker?** retobs answers this with data.

retobs measures what each stage in your retrieval pipeline actually contributes — quality improvement, latency cost, and failure mode — and tells you whether the tradeoff is worth it at your latency budget.

```
Stage Contribution: bm25 → bm25__reranker
┌───────────────┬──────────┬──────────┬──────────────┬────────────────┐
│ Metric        │ Before   │ After    │ Δ            │ Significant?   │
├───────────────┼──────────┼──────────┼──────────────┼────────────────┤
│ recall@10     │ 0.1190   │ 0.1380   │ +0.0190 (+16%)│ q=0.041 ✓    │
│ ndcg@10       │ 0.2640   │ 0.3100   │ +0.0460 (+17%)│ q=0.012 ✓    │
│ Latency P50   │ 2ms      │ 4,057ms  │ +4,055ms     │ —             │
└───────────────┴──────────┴──────────┴──────────────┴────────────────┘
  recall@10 changed +0.0190 (+16.0%) ✓ significant. Latency cost: +4,055ms P50.
  → Adjust your latency budget in the dashboard to explore tradeoffs.
```

What retobs tells you:
1. **Stage attribution** — Recall@10 went from 0.119 → 0.138 (+16%) by adding the reranker. BH-corrected significance: q=0.041 ✓.
2. **Failure diagnosis** — 42% of remaining failures are candidate misses at stage 0. The reranker can't fix what the retriever never found.
3. **Latency-quality tradeoff** — That gain cost 4,000ms/query on CPU. The dashboard lets you slide your latency budget and see the verdict update live.

---

## Benchmark Results

Real numbers on BEIR/nfcorpus (323 queries, 3,633 docs). 95% CIs via paired bootstrap.

| Pipeline                                        | Recall@10                | NDCG@10                  | MRR                      | Latency P50 |
| ----------------------------------------------- | ------------------------ | ------------------------ | ------------------------ | ----------- |
| BM25-only (`rank-bm25`)                         | 0.119 [0.098, 0.141]     | 0.264 [0.233, 0.295]     | 0.468 [0.418, 0.514]     | 2 ms        |
| Dense-only (`all-MiniLM-L6-v2` + FAISS)         | **0.153 [0.129, 0.179]** | **0.310 [0.278, 0.341]** | 0.510 [0.464, 0.555]     | 539 ms*     |
| BM25 → CrossEncoder (`ms-marco-MiniLM-L-6-v2`)  | 0.138 [0.115, 0.163]     | 0.310 [0.275, 0.345]     | **0.530 [0.480, 0.581]** | 4,057 ms**  |

\* Query encoding on CPU; latency drops significantly with GPU or batched encoding.  
\*\* Scoring 100 BM25 candidates through a cross-encoder on CPU; GPU reduces this substantially.

Full data and observations: [results/nfcorpus/README.md](results/nfcorpus/README.md)

---

## How It's Different

| Tool | What it measures |
|------|-----------------|
| BEIR | End-to-end pipeline accuracy on fixed datasets |
| RAGAs / TruLens | Answer quality given retrieved context |
| **retobs** | **Per-stage contribution: what did each stage add in quality, cost, and latency?** |

retobs is not a leaderboard and not an answer evaluator. It's a diagnostic layer between "I have a retrieval pipeline" and "I understand how to improve it."

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

Optionally set a latency budget to get a one-line verdict in CI:

```bash
retobs run --config my_experiment.yaml --latency-budget-ms 1000
```

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
retobs serve     --db PATH [--port N]                     Start dashboard
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

The dashboard frontend is pre-built (`dist/` is checked in), so `retobs serve` works without Node. To modify the React UI:

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
| `langchain`  | langchain-core                          | LangChain adapter (programmatic use)                         |
| `llamaindex` | llama-index-core                        | LlamaIndex adapter (programmatic use)                        |
| `pgvector`   | asyncpg, pgvector                       | Pgvector adapter                                             |
| `llm-judge`  | google-generativeai, anthropic, openai  | LLM-assisted relevance judging                               |

PostgreSQL backend (`asyncpg`) is community-supported and not CI-tested. SQLite is recommended for evaluation workloads.

```bash
pip install -e ".[demo,dashboard,dense,dev,llm-judge]"
```
