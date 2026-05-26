# retrieval-observatory (retobs)

Benchmarking and evaluation framework for hybrid, multi-stage RAG/IR (retrieval) pipelines.

Run a retrieval system against standard datasets, measure recall, ranking quality, and latency, and visualize results in a browser dashboard.

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Minimum — BM25 + dashboard
pip install -e ".[demo,dashboard]"

# With dense retrieval + cross-encoder reranking (needed for multi-stage RAG)
pip install -e ".[demo,dashboard,dense]"
```

---

## Run Configurations

### 1. Single-Stage BM25 Baseline

The simplest configuration: BM25 retrieval on BEIR nfcorpus (~3,600 docs, 323 queries, ~30 seconds).

```bash
retobs run --config examples/beir_demo.yaml
retobs serve --db .retobs/beir_demo.db
```

Open `http://localhost:8000`. You'll see NDCG@10, Recall@K curves, latency percentiles, and a comparison against published BEIR BM25 baselines.

---

### 2. Multi-Stage RAG Pipeline (BM25 → Cross-Encoder Reranking)

The canonical two-stage RAG architecture: BM25 retrieves a wide candidate set (k=100), then a neural cross-encoder reranks for precision (k=20). Requires the `dense` extra.

```bash
pip install -e ".[demo,dashboard,dense]"
retobs run --config examples/nfcorpus_rag_pipeline.yaml
retobs serve --db .retobs/rag_pipeline_demo.db
```

This runs two pipelines side-by-side:
- `bm25_baseline` — single-stage BM25 at k=20
- `bm25_plus_reranker` — BM25 (k=100) → `cross-encoder/ms-marco-MiniLM-L-6-v2` (k=20)

Select both runs in the dashboard sidebar to open the comparison view with p-values. In the single-run view, you'll see the **Pipeline Architecture** diagram showing Stage 0 (Retrieval) → Stage 1 (Reranking) with per-stage NDCG, recall, and latency.

Expected: Stage 1 NDCG@10 ≈ 0.35–0.40, up from BM25-only ≈ 0.31–0.33. Reranking latency is ~5–10× higher than BM25.

---

### 3. Dense Retrieval Comparison (BM25 vs Bi-Encoder)

Compare lexical (BM25) against semantic (MiniLM bi-encoder) retrieval. Both are single-stage.

```bash
pip install -e ".[demo,dashboard,dense]"
retobs run --config examples/nfcorpus_bm25_vs_minilm.yaml
retobs serve --db .retobs/nfcorpus_comparison.db
```

Select both runs in the sidebar to compare NDCG@10 and recall@K side-by-side with statistical significance (paired bootstrap test).

---

### 4. Custom HTTP Endpoint

Wrap any REST retrieval service (Elasticsearch, Weaviate, your own API) without writing Python:

```bash
retobs run --config examples/hybrid_comparison.yaml
retobs serve --db .retobs/hybrid_results.db
```

The `hybrid_comparison.yaml` config sends queries to `http://localhost:8000/search`. Edit the `url` field to point at your service.

---

### 5. Force a Fresh Run (Bypass Cache)

Results are cached by default. Use `--no-cache` to force re-evaluation after changing your retrieval system:

```bash
retobs run --config examples/nfcorpus_rag_pipeline.yaml --no-cache
```

---

### 6. Compare Two Runs from the CLI

```bash
retobs compare <run_id_1> <run_id_2> --db .retobs/rag_pipeline_demo.db
```

Run IDs are printed after each `retobs run` and shown in the dashboard sidebar.

---

## Run the Tests

```bash
pip install -e ".[dev]"
pytest tests/ -x -q
```

49 tests pass; 1 skipped (Postgres, requires `RETOBS_POSTGRES_DSN`).

---

## Writing Your Own Config

Copy any example and edit the `pipelines` block:

```yaml
experiment:
  name: my-experiment

dataset:
  type: beir
  name: nfcorpus          # any BEIR dataset: scifact, nq, hotpotqa, fiqa, ...
  max_queries: 50          # omit to run all queries

pipelines:
  # Single-stage: wrap any REST endpoint
  - id: my_elasticsearch
    stages:
      - type: adapter.http
        url: http://localhost:9200/search
        config: {k: 100}

  # Two-stage: BM25 → cross-encoder reranker
  - id: bm25_plus_reranker
    stages:
      - type: adapter.bm25
        config: {k: 100}
      - type: adapter.hf_crossencoder
        config:
          model: cross-encoder/ms-marco-MiniLM-L-6-v2
          k: 20

  # Dense bi-encoder retrieval
  - id: minilm_dense
    stages:
      - type: adapter.hf_biencoder
        config:
          model: sentence-transformers/all-MiniLM-L6-v2
          k: 100

metrics:
  recall_at_k: [5, 10, 20, 100]
  ndcg_at_k: [10, 20]
  compute_mrr: true
  compute_map: true

execution:
  concurrency: 4
  timeout_seconds: 60
  cache_results: true

output:
  db_path: .retobs/results.db
```

```bash
retobs run --config my_config.yaml
retobs serve --db .retobs/results.db
```

---

## Dashboard Features

| Feature | Description |
|---------|-------------|
| **Pipeline Architecture** | Visual stage-by-stage flow diagram (Retrieval → Reranking) with per-stage NDCG, recall, and latency. Appears automatically for multi-stage runs. |
| **Metric tooltips** | Click the gray `?` next to any metric or column header for a plain-English explanation. |
| **Run comparison** | Select 2+ runs in the sidebar to see a side-by-side table with p-values from a paired bootstrap significance test. |
| **Recall@K curves** | Line chart with error bars and dashed BEIR BM25 reference lines. |
| **Stage Recall Funnel** | Bar chart showing recall at each pipeline stage — reveals how much recall the reranker preserves. |
| **Latency breakdown** | P50/P95/P99 per stage, plus total end-to-end latency for multi-stage pipelines. |
| **Segment analysis** | NDCG@10 broken down by number of relevant docs — reveals where the retriever struggles. |
| **Zero% column** | Fraction of queries where the metric was 0 — exposes bimodal failure modes hidden by the mean. |
| **BEIR baselines** | Published BM25 (Elasticsearch) reference values shown inline for supported datasets. |

---

## CLI Reference

```
retobs run     --config PATH [--no-cache]     Run a benchmark experiment
retobs serve   --db PATH [--port N]           Start dashboard (default: http://localhost:8000)
retobs compare RUN_ID_1 RUN_ID_2 --db PATH   CLI metric comparison with p-values
```

---

## Optional Dependency Groups

| Group        | Installs                                | Use for                                    |
|--------------|----------------------------------------|--------------------------------------------|
| `demo`       | beir, datasets, rank-bm25              | Running BEIR datasets with BM25            |
| `dashboard`  | fastapi, uvicorn                       | Serving the web dashboard                  |
| `dense`      | sentence-transformers, faiss-cpu, torch | Dense bi-encoder + cross-encoder reranking |
| `dev`        | pytest, pytest-asyncio, coverage       | Running tests                              |
| `cohere`     | cohere                                 | CohereRerankAdapter                        |
| `langchain`  | langchain-core                         | LangChainAdapter                           |
| `llamaindex` | llama-index-core                       | LlamaIndexAdapter                          |
| `pgvector`   | asyncpg, pgvector                      | PgvectorAdapter                            |
| `postgres`   | asyncpg                                | PostgresStore backend                      |
| `llm-judge`  | google-generativeai, anthropic, openai | LLM-as-judge grading                       |

Install multiple groups: `pip install -e ".[demo,dashboard,dense,dev]"`