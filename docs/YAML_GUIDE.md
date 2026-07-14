# YAML Pipeline Configuration Guide — retrieval-observatory

**How to use this guide:** Copy the relevant template below and paste it into your LLM with the instruction: "Fill in the placeholders in this retobs YAML config for my pipeline: [describe your pipeline]." The LLM will produce a working config. Then run `retobs validate --config your_config.yaml` to check it before running.

---

## Template 1: Quickest Start — Single Pipeline

Use when: you just want to benchmark one pipeline on your data.

```yaml
experiment:
  name: my-first-benchmark

dataset:
  type: custom
  name: my-dataset
  queries_path: data/queries.jsonl   # FILL IN: path to your queries file
  corpus_path: data/corpus.jsonl     # FILL IN: path to your corpus file

stages:
  retriever:
    type: adapter.bm25               # CHANGE TO: adapter.hf_biencoder for dense, adapter.http for REST API
    config:
      k: 100                         # top-K candidates to retrieve

combinations:
  include:
    - [retriever]

metrics:
  recall_at_k: [1, 5, 10]
  ndcg_at_k: [10]
  mrr: true

output:
  store: sqlite
  db_path: .retobs/results.db
```

---

## Template 2: Compare Two Pipelines (with Stage Attribution)

Use when: you want to know whether adding a reranker is worth it.

```yaml
experiment:
  name: bm25-vs-bm25-rerank

dataset:
  type: custom
  name: my-dataset
  queries_path: data/queries.jsonl
  corpus_path: data/corpus.jsonl

stages:
  bm25:
    type: adapter.bm25
    config:
      k: 100

  rerank:
    type: adapter.hf_crossencoder
    config:
      model: cross-encoder/ms-marco-MiniLM-L-6-v2   # CHANGE: your reranker model
      k: 10                                          # CHANGE: how many to keep after reranking

combinations:
  include:
    - [bm25, rerank]
  ablations: true     # automatically also runs [bm25] alone — required for stage attribution

metrics:
  recall_at_k: [1, 5, 10]
  ndcg_at_k: [10]
  mrr: true

output:
  store: sqlite
  db_path: .retobs/results.db
```

Run: `retobs evaluate --config config.yaml` — the report includes the conclusion, evidence health, affected queries, and per-stage quality/latency evidence.

---

## Template 3: Dense vs BM25 vs Hybrid

Use when: you want a full comparison across retrieval strategies.

```yaml
experiment:
  name: retrieval-strategy-sweep

dataset:
  type: custom
  name: my-dataset
  queries_path: data/queries.jsonl
  corpus_path: data/corpus.jsonl

stages:
  bm25:
    type: adapter.bm25
    config:
      k: 100

  dense:
    type: adapter.hf_biencoder
    config:
      model: sentence-transformers/all-MiniLM-L6-v2  # CHANGE: your embedding model
      k: 100

  hybrid:
    type: adapter.rrf
    config:
      retrievers: [bm25, dense]
      rrf_k: 60

combinations:
  include:
    - [bm25]
    - [dense]
    - [hybrid]

metrics:
  recall_at_k: [1, 5, 10, 20]
  ndcg_at_k: [10]
  mrr: true
  map: true

output:
  store: sqlite
  db_path: .retobs/results.db
```

---

## Template 4: Your Existing REST API

Use when: your retrieval service is already running and you want to benchmark it.

```yaml
experiment:
  name: my-api-benchmark

dataset:
  type: custom
  name: my-dataset
  queries_path: data/queries.jsonl
  corpus_path: data/corpus.jsonl   # still needed for qrel lookup; can be empty if qrels are in queries.jsonl

stages:
  my_retriever:
    type: adapter.http
    url: http://localhost:8080/retrieve   # CHANGE: your service URL
    config:
      k: 100
      id_field: id            # CHANGE: the field name for document ID in your response
      text_field: text        # CHANGE: the field name for document text in your response
      score_field: score      # CHANGE: the field name for relevance score in your response

combinations:
  include:
    - [my_retriever]

metrics:
  recall_at_k: [1, 5, 10]
  ndcg_at_k: [10]
  mrr: true

output:
  store: sqlite
  db_path: .retobs/results.db
```

Your service receives: `POST {"query": "question text", "k": 100}`
Your service must return: `{"documents": [{"id": "doc1", "text": "...", "score": 0.9}, ...]}`
or just a list: `[{"id": "doc1", "text": "...", "score": 0.9}]`

---

## Template 5: BEIR Dataset (No Custom Data Needed)

Use when: you want to benchmark on a standard BEIR dataset immediately.

```yaml
experiment:
  name: beir-nfcorpus-sweep

dataset:
  type: beir
  name: nfcorpus     # CHANGE: nfcorpus | scifact | fiqa | msmarco | trec-covid | ...
  split: test
  max_queries: 100   # REMOVE for full test split; use for fast iteration

stages:
  bm25:
    type: adapter.bm25
    config: {k: 100}

  dense:
    type: adapter.hf_biencoder
    config:
      model: sentence-transformers/all-MiniLM-L6-v2
      k: 100

combinations:
  include:
    - [bm25]
    - [dense]
  ablations: false

metrics:
  recall_at_k: [1, 5, 10]
  ndcg_at_k: [10]

output:
  store: sqlite
  db_path: .retobs/beir_nfcorpus.db
```

Requires: `pip install "retrieval-observatory[beir,dense]"`

---

## Template 6: Full Production Config (All Options)

Use as a reference for every available option.

```yaml
experiment:
  name: production-sweep                 # experiment name; appears in dashboard

dataset:
  type: custom                           # beir | custom | http
  name: my-production-dataset
  queries_path: data/queries.jsonl       # required
  corpus_path: data/corpus.jsonl         # required for local retrievers
  timestamp_field: published_at          # optional: enables temporal_recall@K metrics
  metadata_fields: [category, source]    # optional: enables segment analysis in dashboard

stages:
  # First-stage retriever options (pick one or more)
  bm25:
    type: adapter.bm25
    config:
      k: 100                             # number of candidates to return

  dense:
    type: adapter.hf_biencoder
    config:
      model: sentence-transformers/all-MiniLM-L6-v2
      k: 100
      batch_size: 64                     # optional: inference batch size

  cohere_rerank:
    type: adapter.cohere_rerank
    config:
      model: rerank-english-v3.0
      k: 10

  my_api:
    type: adapter.http
    url: http://localhost:9000/search
    config:
      k: 100
      id_field: doc_id
      text_field: content
      score_field: relevance_score

combinations:
  include:
    - [bm25]
    - [dense]
    - [bm25, cohere_rerank]
  ablations: true                        # auto-generates prefix pipelines for attribution

metrics:
  recall_at_k: [1, 5, 10, 20]
  precision_at_k: [5, 10]
  ndcg_at_k: [10]
  mrr: true
  map: true
  latency_percentiles: [50, 95, 99]

execution:
  concurrency: 4                         # parallel query execution
  timeout_seconds: 60                    # per-query timeout
  cache_results: true                    # stage-level caching; use --no-cache to disable

costs:
  bm25:
    per_1k_queries: 0.05               # estimated cost model for tradeoff analysis
  cohere_rerank:
    per_1k_queries: 2.00

labels:
  mode: gold                           # gold (default) | llm_judge | pooled_llm_judge
  # Only needed if mode != gold:
  judge: gemini                        # gemini | openai | anthropic
  model: gemini-2.0-flash
  cache_path: .retobs/llm_judge_cache.db

output:
  store: sqlite
  db_path: .retobs/production.db
  export: [json]                       # also write JSON exports alongside SQLite
```

---

## Dataset File Formats

### queries.jsonl (one JSON object per line)

```json
{"query_id": "q1", "text": "What changed in the refund policy?", "relevant_doc_ids": {"doc_17": 2, "doc_22": 1}}
{"query_id": "q2", "text": "How long does shipping take?", "relevant_doc_ids": ["doc_8", "doc_15"]}
```

- `query_id`: unique string
- `text`: the query string
- `relevant_doc_ids`: either a dict `{doc_id: grade}` (2=highly relevant, 1=relevant, 0=not relevant) or a list of doc IDs (treated as grade 2)
- `temporal_anchor` (optional): ISO datetime string — enables temporal recall metrics

### corpus.jsonl (one JSON object per line)

```json
{"id": "doc_17", "title": "Refund Policy Update", "text": "Refunds are now processed within 7 days of return receipt.", "timestamp": "2024-01-10T00:00:00"}
{"id": "doc_8", "title": "Shipping FAQ", "text": "Standard shipping takes 3-5 business days."}
```

- `id`: unique string (must match `relevant_doc_ids` in queries)
- `text`: document content (required)
- `title` (optional): shown in dashboard and used by some retrievers
- `timestamp` (optional): ISO datetime — enables temporal analysis when `timestamp_field` is set in config

### qrels.jsonl (alternative to inline relevant_doc_ids)

```json
{"query_id": "q1", "doc_id": "doc_17", "grade": 2}
{"query_id": "q1", "doc_id": "doc_22", "grade": 1}
```

TREC-style qrels.tsv also supported: `query_id \t 0 \t doc_id \t grade`

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `adapter.hf_biencoder` fails with import error | Run `pip install "retrieval-observatory[dense]"` |
| Stage attribution table is missing | Add `ablations: true` to combinations |
| Dashboard shows no data | Check `db_path` matches the path passed to `retobs serve --db` |
| All queries show `candidate_miss` | Your corpus `id` field doesn't match `relevant_doc_ids` in queries — check IDs match exactly |
| `retobs validate` reports missing corpus | Use absolute paths or run retobs from the directory containing your data |

---

## Generating Configs with an LLM

Paste this prompt into ChatGPT, Claude, or Gemini:

```
I want to benchmark my retrieval pipeline using retrieval-observatory (retobs).
Here is the retobs YAML format guide: [paste this entire YAML_GUIDE.md file]

My pipeline:
- First stage: [describe your retriever, e.g. "BM25 on our internal search API at localhost:8000/search"]
- Second stage: [describe your reranker if any, e.g. "Cohere rerank-english-v3.0"]
- Dataset: [describe your data, e.g. "custom JSONL with ~5000 documents and 300 queries"]
- Goal: [what you want to compare, e.g. "whether the reranker is worth the added latency"]

Generate a complete retobs YAML config for this pipeline.
```

Then: `retobs validate --config generated_config.yaml` to catch any issues before running.
