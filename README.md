# retrieval-observatory (retobs)

Benchmarking and evaluation framework for multi-stage RAG/IR retrieval pipelines. Run a retrieval system against standard datasets, measure recall, ranking quality, and latency, and visualize results in a browser dashboard.

---

## Quick Demo (BM25 on BEIR nfcorpus)

```bash
# 1. Create venv and install (first time only)
python -m venv .venv
.venv/bin/pip install -e ".[demo,dashboard]"

# 2. Run BM25 baseline on nfcorpus (~3,600 docs, 323 queries)
.venv/bin/retobs run --config examples/beir_demo.yaml

# 3. Start the dashboard and open http://localhost:8000
.venv/bin/retobs serve --db .retobs/beir_demo.db
```

The `run` command downloads `beir/nfcorpus` from HuggingFace on first use (~10 MB), runs BM25 retrieval over all test queries, computes metrics, and writes results to `.retobs/beir_demo.db`. The `serve` command starts a FastAPI server that serves the React dashboard at `http://localhost:8000`.

---

## Run the Tests

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/unit/ -v
.venv/bin/pytest tests/integration/ -v
```

49 tests pass; 1 skipped (Postgres, requires `RETOBS_POSTGRES_DSN`).

---

## Writing Your Own Config

Copy `examples/beir_demo.yaml` and change the pipeline stages:

```yaml
experiment:
  name: my-experiment

dataset:
  name: beir/scifact     # any of the 18 BEIR datasets
  split: test

pipelines:
  - id: my_retriever
    stages:
      - type: adapter.http          # wrap any REST endpoint
        config:
          url: http://localhost:9200/search
          retriever_id: elasticsearch

metrics:
  recall_at_k: [1, 5, 10]
  mrr: true
  ndcg_at_k: [10]
  latency_percentiles: [50, 95, 99]

output:
  store: sqlite
  db_path: .retobs/results.db
```

Run with `.venv/bin/retobs run --config my_config.yaml`.

---

## CLI Reference

```
retobs run    --config PATH        Run a benchmark experiment
retobs serve  --db PATH            Start dashboard server (default port 8000)
retobs compare RUN_ID_1 RUN_ID_2  Print side-by-side metric comparison
```

---

## Optional Dependency Groups


| Group        | Installs                                | Use for                         |
| ------------ | --------------------------------------- | ------------------------------- |
| `demo`       | beir, datasets, rank-bm25               | Running BEIR datasets with BM25 |
| `dashboard`  | fastapi, uvicorn                        | Serving the web dashboard       |
| `dev`        | pytest, pytest-asyncio, coverage, respx | Running tests                   |
| `cohere`     | cohere                                  | CohereRerankAdapter             |
| `hf`         | sentence-transformers, torch            | HFCrossEncoderAdapter           |
| `langchain`  | langchain-core                          | LangChainAdapter                |
| `llamaindex` | llama-index-core                        | LlamaIndexAdapter               |
| `pgvector`   | asyncpg, pgvector                       | PgvectorAdapter                 |
| `postgres`   | asyncpg                                 | PostgresStore backend           |
| `llm-judge`  | google-generativeai, anthropic, openai  | LLM-as-judge grading            |


Install multiple groups: `.venv/bin/pip install -e ".[demo,dashboard,dev]"`