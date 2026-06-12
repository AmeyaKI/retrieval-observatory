# retrieval-observatory (retobs)

[![PyPI version](https://img.shields.io/pypi/v/retrieval-observatory.svg)](https://pypi.org/project/retrieval-observatory/)

Most RAG evaluation tools score end-to-end answer quality and stop there. They don't tell you **which stage helped**, **what it cost in latency**, or **which queries will fail before you run retrieval**. retobs is an open-source multi-stage retrieval benchmark and local dashboard that measures per-stage contribution, failure diagnosis, latency–quality tradeoffs, and query difficulty — so you can decide whether to add that reranker (or switch to dense) with evidence, not intuition.

---

## Benchmark Results (3 BEIR datasets, 1,271 queries)

| Dataset | BM25 NDCG@10 | Dense NDCG@10 | Improvement | Pareto winner |
|---------|-------------|--------------|-------------|---------------|
| NFCorpus (biomedical) | 0.264 | **0.310** | +17.6% | dense_only, bm25 |
| SciFact (scientific claims) | 0.544 | **0.640** | +17.7% | dense_only |
| FiQA (financial QA) | 0.159 | **0.369** | **+132%** | dense_only |

Dense retrieval (`all-MiniLM-L6-v2`) is Pareto-optimal on SciFact and FiQA — matching or beating cross-encoder reranking at **133–228× lower latency**. Full numbers, confidence intervals, and failure analysis: [RESULTS.md](RESULTS.md)

---

## What retobs tells you

**Stage attribution** — what did each stage add?

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

- **Failure diagnosis** — Candidate misses, lexical mismatches, reranker drops — labeled per query.
- **Latency–quality tradeoff** — Pareto frontier; see whether reranking is worth it at your latency budget.
- **Query difficulty prediction** — Predict which queries will fail before running retrieval.

---

## How It's Different

| Tool | What it measures |
|---|---|
| BEIR | End-to-end pipeline accuracy on fixed datasets |
| RAGAs / TruLens | Answer quality given retrieved context |
| **retobs** | **Per-stage contribution: what did each stage add in quality, cost, and latency?** |

retobs is not a leaderboard and not an answer evaluator. It's a diagnostic layer between "I have a retrieval pipeline" and "I understand how to improve it."

---

## Install

```bash
pip install "retrieval-observatory[demo,dashboard,dense]"
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

**From a git clone**:

```bash
git clone https://github.com/AmeyaKI/retrieval-observatory.git && cd retrieval-observatory
pip install -e ".[demo,dashboard,dense]"
retobs validate --config examples/quickstart_scifact.yaml
retobs run --config examples/quickstart_scifact.yaml
retobs serve --db .retobs/quickstart_scifact.db
```

Open `http://localhost:4000`.

---

## Define Your Pipeline in YAML

```yaml
experiment:
  name: my-rag-sweep

dataset:
  type: custom
  queries_path: data/queries.jsonl
  corpus_path: data/corpus.jsonl

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
  ablations: true    # auto-generates [bm25] and [dense] prefix pipelines

metrics:
  recall_at_k: [1, 5, 10, 20]
  ndcg_at_k: [10]
  mrr: true

output:
  store: sqlite
  db_path: .retobs/results.db
```

retobs expands `ablations: true` into all needed pipeline variants automatically. Want to paste this into your LLM and have it generate a config for your pipeline? See [BREAKDOWN.md — YAML Configuration](BREAKDOWN.md#yaml-pipeline-configuration) for the full format guide with every option explained.

---

## Run It

```bash
# Generate a starter config
retobs init --mode bm25+reranker --output my_experiment.yaml

# Validate before running (catches schema errors, missing files)
retobs validate --config my_experiment.yaml

# Run the benchmark (stage attribution printed automatically)
retobs run --config my_experiment.yaml

# Open the dashboard
retobs serve --db .retobs/results.db
```

---

## Forge — Synthetic Stress Datasets

Forge generates targeted hard queries from your own corpus — exposing failure modes that standard benchmarks don't cover.

```bash
# Scan corpus for temporal/alias failure patterns (no LLM needed)
retobs forge scan --corpus data/corpus.jsonl

# Generate a full stress-test dataset
GOOGLE_API_KEY=your-key retobs forge run \
  --corpus data/corpus.jsonl \
  --output forge_output/ \
  --n-per-type 5
```

Forge detects temporal confusion (two documents about the same entity at different times) and alias mismatches (docs using "AWS" vs "Amazon Web Services") and generates queries designed to probe those exact failure modes. Output is BEIR-compatible and can be dropped straight into `retobs run`.

---

## CLI Reference

```bash
retobs init      --mode MODE --output PATH        Generate starter config
retobs validate  --config PATH                    Validate config and dataset
retobs run       --config PATH [--no-cache]       Run benchmark
retobs serve     --db PATH [--port N]             Start dashboard
retobs compare   RUN_ID_1 RUN_ID_2 --db PATH      Side-by-side run comparison
retobs inspect   RUN_ID --query QUERY_ID          Debug per-query results

retobs classifier train   --dataset DATASET_NAME  Train difficulty classifier
retobs forge scan   --corpus PATH                 Scan for failure patterns
retobs forge run    --corpus PATH --output DIR    Generate synthetic eval set
```

Full reference with all flags: [BREAKDOWN.md — CLI Reference](BREAKDOWN.md#cli-reference)

---

## Going Deeper

- [RESULTS.md](RESULTS.md) — Full benchmark results across 3 BEIR datasets with statistical analysis
- [BREAKDOWN.md](BREAKDOWN.md) — Complete technical reference: all adapters, YAML options, dataset formats, dashboard features
- [results/BENCHMARK_ANALYSIS.md](results/BENCHMARK_ANALYSIS.md) — Deep-dive into the 4-pipeline sweep: Pareto analysis, classifier calibration, statistical methodology
