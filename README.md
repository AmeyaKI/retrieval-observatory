# retobs

[![PyPI version](https://img.shields.io/pypi/v/retrieval-observatory)](https://pypi.org/project/retrieval-observatory/)

Most RAG evaluation tools score end-to-end answer quality and stop there. **retobs** is a local-first **retrieval reliability platform** — it measures per-operator contribution, diagnoses why queries fail, generates corpus-specific stress tests, observes production retrieval via traces, and recommends fixes when quality regresses.

The fundamental unit is the **query**: Forge origin → benchmark scores → production trace matches → Advisor recommendations, all linked by query lineage.

Retrieval pipelines are modeled as an **operator DAG** (`RetrievalTraceV2`), not a flat list of stages — sources, fusion, expansion, filters, transforms, rerankers, boosts, and gates are each a typed operator span with parent links, so gated/conditional production pipelines (not just linear `bm25 → rerank` chains) can be traced and attributed accurately. Every attribution result carries a **replay tier** (`EXACT` / `OBSERVED_ABLATION` / `NOT_REPLAYABLE`) — retobs never reports a fabricated delta when the counterfactual can't actually be replayed.

---

## Quickstart — one command, under 5 minutes, no API keys

```bash
pip install "retrieval-observatory[demo,dashboard]"
retobs quickstart
```

Open `http://localhost:4000`. Forge scans a synthetic corpus, builds stress-test queries, runs a BM25 benchmark, seeds TraceLens traces with failure labels, and opens the dashboard — all in one command.

**Full platform demo** (more data, Advisor comparison, multi-stage ablation):

```bash
pip install "retrieval-observatory[demo,dashboard,dense]"
retobs demo --db .retobs/demo/results.db
retobs serve --db .retobs/demo/results.db
```

Use `--keep-db` to append instead of wiping the DB. Use `retobs demo --full` for an additional multi-stage ablation benchmark.

---

## Quickstart — benchmark your pipeline in Python (no YAML)

Wrap your existing retriever and benchmark it in a few lines. Same engine, metrics, diagnostics, and dashboard as the CLI path.

```python
import retrieval_observatory as ro

@ro.retriever
def my_pipeline(query: str) -> list[str]:        # returns ranked doc ids
    return my_vectordb.search(query, k=20)

report = ro.benchmark(my_pipeline, dataset="beir/scifact", max_queries=100)
report.show()        # per-stage metrics + failure diagnostics
report.serve()       # open the dashboard on this run

# The value-preserving form: per-stage contribution + candidate_miss vs reranker_drop
report = ro.benchmark([my_retriever, my_reranker], queries=QUERIES, corpus=CORPUS)
```

A single callable is one stage; pass a list `[retriever, reranker, ...]` for per-stage attribution. Stages can be plain callables (`-> list[id]`, `list[(id, score)]`, or `list[Document]`), objects with `.retrieve()`/`.rerank()`, or LangChain / LlamaIndex retrievers. Full SDK reference: [BREAKDOWN.md — Python SDK](BREAKDOWN.md#python-sdk) and [examples/sdk_quickstart.py](examples/sdk_quickstart.py).

**No labels?** Synthesize a test set (queries + ground truth) from your corpus, or grade retrieved docs on the fly with an LLM judge:

```python
testset = ro.generate_testset(corpus)                       # rule-based, no API key
ro.benchmark(my_pipeline, dataset=testset)

ro.benchmark(my_pipeline, queries=queries, corpus=corpus,   # zero ground truth
             labels="llm-judge", judge="gemini")
```

`ro.generate_testset(...)` is free/rule-based and fast but lower coverage; `labels="llm-judge"` costs API tokens and is slower, but can recover relevant docs that extractive labels miss.

**CI gate** — fail the build on a significant regression via the bundled pytest plugin:

```python
def test_no_regression(retobs):
    candidate = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS)
    candidate.assert_no_regression("GOLDEN_RUN_ID", metric="ndcg")
```

Details: [docs/informative/ci_gating.md](docs/informative/ci_gating.md).

---

## Real-data integration notes

### Dataset formats (custom JSONL + qrels)

```json
{"id":"doc_1","title":"Optional title","text":"Document text","timestamp":"2025-01-01T00:00:00Z"}
{"query_id":"q_1","text":"query text","relevant_doc_ids":["doc_1"]}
{"query_id":"q_2","text":"graded query","relevant_doc_ids":{"doc_9":2,"doc_3":1}}
```

- `corpus.jsonl`: one JSON object per document (`id`, `text`; `title`/`timestamp` optional).
- `queries.jsonl`: one JSON object per query (`query_id`, `text`, `relevant_doc_ids`).
- `relevant_doc_ids` supports binary list (`["doc"]`) or graded dict (`{"doc": 2}`).
- Optional `qrels_path` supports JSONL (`query_id`, `doc_id`, `grade|score`) and TREC text lines.
- Internal qrels are normalized to `{query_id: {doc_id: grade_int}}`; binary relevance maps to grade `1`.

### Custom retriever integration options

- **SDK callable path:** pass a Python callable (or `[retriever, reranker]`) to `ro.benchmark(...)`.
- **Adapter protocol path:** provide objects implementing `.retrieve(query)` / `.rerank(query, docs)`.
- **Any REST retriever:** use `adapter.http`; response field names are configurable via `id_field`, `text_field`, `score_field`.

### Production tracing recipe

```python
import retrieval_observatory as ro
from retrieval_observatory.tracing.integrations.fastapi import instrument_fastapi, get_trace

recorder = ro.init(service="search-api", db=".retobs/prod.db")
instrument_fastapi(app, recorder)

@app.get("/search")
async def search(q: str, request: Request):
    t = get_trace(request)
    if t is None:  # route excluded / sampling skipped
        return baseline_search(q)
    with t.stage("bm25") as s:
        s.results = bm25_ids(q)
    with t.stage("rerank") as s:
        s.results = rerank_ids(q, s.results)
    return s.results
```

`get_trace()` can return `None` when tracing is excluded for the route (or sampled out); your handler should continue normally.

Each `t.stage(...)` call becomes a typed `OperatorSpan` in a `RetrievalTraceV2` DAG (`ro.init()` returns a V2-native recorder by default) — gates, fusion, expansion, and reranking are all first-class operator types, not a flattened list, so multi-lane production pipelines are attributed correctly. See [BREAKDOWN.md — Trace-Native Model & Attribution](BREAKDOWN.md#trace-native-model--attribution).

### Current storage limitation

Dashboard serving now accepts SQLite paths and Postgres DSNs. Postgres support is still single-tenant and local-first; authentication/tenant isolation are intentionally out of scope.

### Deployment

A `Dockerfile` and `docker-compose.yml` are provided for a self-hosted, single-tenant `retobs serve` deployment (with an optional Postgres service via Compose profiles). No auth/multi-tenancy is included by design — see [Capability matrix](#capability-matrix).

---

## Capability matrix

What retobs does and does not support today, traced to code. "Not supported as of now" means
the capability is genuinely absent — not silently approximated. Where a limit is silent at
runtime, that is called out so a result is never trusted past what the engine actually computed.

| Capability | Status | Detail |
|------------|--------|--------|
| **Corpus storage** | RAM-only | In-process adapters hold the whole corpus in memory (`datasets/inmemory.py`, `adapters/bm25_adapter.py`, `adapters/hf_biencoder_adapter.py`). Practical ceiling ≈100–500k docs. Streaming / sharded corpora are **not supported as of now**. |
| **Fusion (hybrid retrieval)** | N-way, DAG-attributed | `ro.fuse([...])` combines any ≥2 retrievers as a first-class `FUSE` operator span with per-arm provenance (`tracing/lift.py`, `tracing/model_v2.py`). Removing a source arm re-runs RRF over the remaining arms for counterfactual attribution. Nested/multiple fusion stages inside a benchmark YAML pipeline are still **not supported as of now** — use `@observe` to trace a nested-fusion production pipeline instead. |
| **Metadata / temporal filters** | HTTP, BM25, HF bi-encoder, pgvector, Qdrant | `adapters/http_adapter.py`, `adapters/bm25_adapter.py`, `adapters/hf_biencoder_adapter.py` support equality filtering on `Query.filters`; `adapters/pgvector_adapter.py` builds a SQL `WHERE` clause; `adapters/qdrant_adapter.py` builds a native Qdrant `Filter`. Range filters (`>=`, `<=`, `in`) are **not supported as of now** — equality only. |
| **Relevance scale** | Binary + graded | Graded qrels with arbitrary integer grades are supported for NDCG via standard exponential gain `2^grade − 1` (`metrics/ranking.py:ndcg_at_k_graded`, wired in `metrics/engine.py`). Recall / MAP / MRR are binary: any grade > 0 counts as relevant. |
| **Pipeline routing** | Linear (benchmarks) + operator DAG (production tracing) | A YAML/SDK benchmark pipeline is still a stage-0 retriever followed by rerankers (`runner/execute.py`). Gated, conditional, and parallel-lane production pipelines are supported today by instrumenting with `@observe`/`ro.init()`, which emits a `RetrievalTraceV2` operator DAG with `parent_ids` — the dashboard renders and attributes this DAG directly. A declarative YAML DAG-config runner (design, don't just observe, a complex pipeline) is **not supported as of now**. |
| **Built-in adapters** | 8 | BM25, HF bi-encoder, pgvector, Qdrant, Cohere rerank, LangChain, LlamaIndex, HTTP (`adapters/`). Pinecone / Weaviate remain unsupported (use the HTTP adapter or implement the retriever protocol directly). |
| **Result storage backend** | SQLite + Postgres (single-tenant) | Dashboard registry accepts SQLite files and Postgres DSNs (`dashboard/registry.py`). Postgres serving is supported for benchmark and trace-native APIs; deployment posture remains single-tenant/no-auth by default. |
| **Operator attribution** | Segment × operator, replay-tiered | `tracing/attribution.py` computes per-segment marginal contribution (recall/NDCG/precision/MRR/MAP) for every operator, with bootstrap CIs, BH-corrected significance, low-power flags, and an explicit replay tier so `NOT_REPLAYABLE` operators never report a fabricated delta. |
| **Miss attribution** | Operator-level + graph-aware | `tracing/replay.py::attribute_miss` explains why a relevant doc didn't surface (dropped by a named operator, never retrieved, or reachable via a document-graph edge that wasn't traversed) via `corpus/graph.py::EdgeStore`. |

---

## Four Modes


| Mode           | Question                        | What you get                                                        |
| -------------- | ------------------------------- | ------------------------------------------------------------------- |
| **Benchmarks** | What happened? Why?             | Per-stage metrics, failure labels, query explorer, Pareto tradeoffs |
| **Forge**      | What failures haven't we found? | Temporal + alias stress queries from your corpus                    |
| **TraceLens**  | What's happening in production? | Live traces, drift, hotspots (suspected failures — no ground truth) |
| **Advisor**    | What should I do next?          | Regression detection, rule-based recommendations, reliability score |


**Query lineage** — `#/query/<query_id>` links Forge origin, benchmark runs, and categorical production trace matches.

---

## Benchmark Results from v0.1.2(3 BEIR datasets, 1,271 queries)


| Dataset                     | BM25 NDCG@10 | Dense NDCG@10 | Improvement | Pareto winner    |
| --------------------------- | ------------ | ------------- | ----------- | ---------------- |
| NFCorpus (biomedical)       | 0.264        | **0.310**     | +17.6%      | dense_only, bm25 |
| SciFact (scientific claims) | 0.544        | **0.640**     | +17.7%      | dense_only       |
| FiQA (financial QA)         | 0.159        | **0.369**     | **+132%**   | dense_only       |


Dense retrieval (`all-MiniLM-L6-v2`) is Pareto-optimal on SciFact and FiQA — matching or beating cross-encoder reranking at **133–228× lower latency**. Full numbers: [RESULTS.md](RESULTS.md)

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

- **Failure diagnosis** — candidate misses, lexical mismatches, reranker drops — labeled per query.
- **Latency–quality tradeoff** — Pareto frontier; see whether reranking is worth it at your latency budget.
- **Query difficulty classifier** — train on diagnostic labels from past runs (`retobs classifier train`) to segment eval sets by difficulty tier.

---

## How It's Different


| Tool            | What it measures                                                                     |
| --------------- | ------------------------------------------------------------------------------------ |
| BEIR            | End-to-end pipeline accuracy on fixed datasets                                       |
| RAGAs / TruLens | Answer quality given retrieved context                                               |
| **retobs**      | **Per-stage contribution, failure taxonomy, stress tests, prod traces, regressions** |


retobs is not a leaderboard and not an answer evaluator. It's a diagnostic layer between "I have a retrieval pipeline" and "I understand how to improve it."

---

## Install

```bash
pip install "retrieval-observatory[demo,dashboard,dense]"
```

```python
import retrieval_observatory as ro
```

---

## SciFact quickstart (single benchmark)

```bash
CFG="$(python -c 'from retrieval_observatory import EXAMPLES_DIR; print(EXAMPLES_DIR / "quickstart_scifact.yaml")')"
retobs validate --config "$CFG"
retobs run --config "$CFG"
retobs serve --db .retobs/quickstart_scifact.db
```

From a git clone: `pip install -e ".[demo,dashboard,dense]"` then use `examples/quickstart_scifact.yaml`.

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

Paste this into your LLM to generate a config for your pipeline. Full format: [BREAKDOWN.md — YAML Configuration](BREAKDOWN.md#yaml--pipeline-configuration) and [YAML_GUIDE.md](YAML_GUIDE.md).

---

## Advisor & CI

```bash
# Detect regressions (non-zero exit = significant quality drop)
retobs advisor check --baseline RUN_A --candidate RUN_B --db .retobs/results.db

# Rule-based recommendations for a run
retobs advisor recommend --run RUN_ID --db .retobs/results.db

# Golden set for CI gates
retobs advisor golden create --set my-golden --queries queries.json
```

Template workflow: [examples/retrieval-ci.yml](examples/retrieval-ci.yml). For Python pipelines, the bundled pytest plugin turns this into a one-line assertion — see [docs/informative/ci_gating.md](docs/informative/ci_gating.md).

---

## TraceLens (production observability)

```bash
# Seed sample traces (or use retobs demo)
retobs tracelens demo --service demo --db .retobs/results.db

# Live FastAPI tracing (writes to demo DB by default)
RETOBS_LATENCY_BUDGET_MS=100 python examples/fastapi_search/app.py
curl "http://localhost:8080/search?q=BM25+retrieval"
curl "http://localhost:8080/search?q=xyzzy-nonexistent"   # triggers empty_candidates
curl "http://localhost:8080/search?q=hybrid+search&slow=1" # triggers latency_over_budget
```

Production traces use **suspected** failure signals (label-free, rule-based proxies), not measured Recall:
- `empty_candidates` — retriever returned zero results
- `latency_over_budget` — total latency exceeded the configured budget
- `high_churn` — candidate set changed ≥70% between pipeline stages
- `low_confidence` — top document score at or below threshold

These are heuristic classifiers, not learned models. Measured quality lives in Benchmarks + Forge.

### LangChain & LlamaIndex — zero-touch tracing

Add one line to an existing chain or query engine; retobs captures traces automatically:

```python
# LangChain (requires: pip install retrieval-observatory[langchain])
from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback

cb = RetobsLangChainCallback(recorder, pipeline_id="my-chain")
chain.invoke(query, config={"callbacks": [cb]})  # one line, zero manual stage wrapping

# LlamaIndex (requires: pip install retrieval-observatory[llamaindex])
from llama_index.core.callbacks import CallbackManager
from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexCallback

cb = RetobsLlamaIndexCallback(recorder, pipeline_id="my-index")
Settings.callback_manager = CallbackManager([cb])
```

Both integrate via real `BaseCallbackHandler` subclasses — `RetobsLangChainCallback` inherits `langchain_core.callbacks.base.BaseCallbackHandler`, `RetobsLlamaIndexCallback` inherits `llama_index.core.callbacks.base_handler.BaseCallbackHandler`. Multi-retriever chains produce one stage per retriever without double-counting.

Runnable examples: [examples/langchain_search/app.py](examples/langchain_search/app.py), [examples/llamaindex_search/app.py](examples/llamaindex_search/app.py).

---

## Forge — Synthetic Stress Datasets

```bash
retobs forge scan --corpus data/corpus.jsonl
GOOGLE_API_KEY=your-key retobs forge run --corpus data/corpus.jsonl --output forge_output/
```

Forge detects temporal confusion and alias mismatches and generates queries designed to probe those failure modes.

---

## CLI Reference

```bash
retobs demo       [--db PATH] [--full]              Full reliability platform demo
retobs init       --mode MODE --output PATH          Generate starter config
retobs validate   --config PATH                       Validate config and dataset
retobs run        --config PATH [--no-cache]          Run benchmark
retobs serve      --db PATH [--port N]                Start dashboard
retobs compare    RUN_A RUN_B --db PATH               Side-by-side comparison
retobs inspect    RUN_ID --query QUERY_ID             Per-query debug

retobs advisor check|recommend|golden ...           Regressions, recommendations, CI gates
retobs forge scan|run|list ...                      Stress-test dataset generation
retobs tracelens demo|stats|purge ...               Production trace observability
retobs classifier train|report|predict ...          Query difficulty classifier
```

Full reference: [BREAKDOWN.md — CLI Reference](BREAKDOWN.md#cli-reference)

---

## Going Deeper

- [docs/USAGE.md](docs/USAGE.md) — Full usage guide: every CLI command, the Python SDK, wiring retobs into an existing (including hybrid/multi-stage) RAG pipeline, the dashboard, and metrics reference
- [BREAKDOWN.md](BREAKDOWN.md) — Complete architecture reference: subsystems, data flow, trace-native model, adapters, metrics, storage, dashboard API
- [CHANGELOG.md](CHANGELOG.md) — Full version history (v0.1.0 → v0.4.0)
- [RESULTS.md](RESULTS.md) — Full benchmark results across 3 BEIR datasets
- [results/BENCHMARK_ANALYSIS.md](results/BENCHMARK_ANALYSIS.md) — Deep-dive: Pareto analysis, statistical methodology
- [YAML_GUIDE.md](YAML_GUIDE.md) — Six copy-paste YAML templates and an LLM prompt for generating configs
- [FUTURE_EDITS.md](FUTURE_EDITS.md) — Planned Phase 5–7 work: DAG runner, per-lane eval, sweeps

