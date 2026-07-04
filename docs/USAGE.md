# Using retobs

This is the practical, task-oriented guide: install it, wire it into a pipeline you already
have, read the results. For architecture internals see [BREAKDOWN.md](../BREAKDOWN.md); for the
full CLI/config reference tables see [BREAKDOWN.md — CLI Reference](../BREAKDOWN.md#cli-reference)
and [YAML_GUIDE.md](../YAML_GUIDE.md).

## Table of contents

1. [Install](#install)
2. [Core concepts](#core-concepts)
3. [Two ways in: YAML vs Python SDK](#two-ways-in-yaml-vs-python-sdk)
4. [Wiring retobs into a pipeline you already have](#wiring-retobs-into-a-pipeline-you-already-have)
5. [Hybrid, multi-stage, and complex pipelines](#hybrid-multi-stage-and-complex-pipelines)
6. [Production tracing (live services)](#production-tracing-live-services)
7. [The dashboard](#the-dashboard)
8. [Metrics and attribution reference](#metrics-and-attribution-reference)
9. [Datasets and qrels](#datasets-and-qrels)
10. [Full CLI reference](#full-cli-reference)
11. [CI regression gating](#ci-regression-gating)
12. [Troubleshooting](#troubleshooting)

---

## Install

```bash
pip install "retrieval-observatory[demo,dashboard]"      # BM25 + dashboard, no heavy ML deps
pip install "retrieval-observatory[demo,dashboard,dense]" # + real dense retrieval / cross-encoder rerank
```

```python
import retrieval_observatory as ro
```

Extras (add only what you need): `dense` (sentence-transformers + faiss, for `adapter.hf_biencoder`
/ `adapter.hf_crossencoder`), `cohere`, `pgvector`, `qdrant`, `langchain`, `llamaindex`, `forge`
(LLM-backed stress-test generation), `tracelens` (production trace enrichment), `classifier`,
`dev` (test suite). Full list: [pyproject.toml](../pyproject.toml).

---

## Core concepts

| Concept | What it means in retobs |
|---|---|
| **Query** | One evaluation input: text, optional `k`, optional metadata/filters. |
| **Document** | One corpus item or retrieval result: `id`, `text`, `score`, `rank`. |
| **Stage / Operator** | One step in a pipeline — a retriever, a fusion, a rerank, a filter, a boost, a gate. |
| **Pipeline** | An ordered list of stages. Stage 0 retrieves from the full corpus; later stages rerank the prior stage's output. |
| **Run** | One execution of one or more pipelines over one dataset. Has a `run_id`. |
| **Trace** | The operator-level record of *one query through one pipeline* — `RetrievalTraceV2`, a DAG of `OperatorSpan`s (`SOURCE`, `FUSE`, `EXPAND`, `FILTER`, `TRANSFORM`, `RERANK`, `BOOST`, `GATE`). Every benchmark run and every production request produces one. |
| **Attribution** | "Which operator helped or hurt, and by how much" — computed by replaying a trace with one operator counterfactually removed. Every result carries a **replay tier**: `EXACT` (deterministic, safe to trust), `OBSERVED_ABLATION` (non-deterministic operator, e.g. an LLM reranker — trust the direction, not the exact number), `NOT_REPLAYABLE` (can't be replayed at all — reported as `indeterminate`, never a fabricated number). |

The fundamental unit that ties everything together is the **query**: the same `query_id` links a
Forge-generated stress query, a benchmark score, a production trace match, and an Advisor
recommendation.

---

## Two ways in: YAML vs Python SDK

Both routes call the exact same executor (`runner/execute.py::execute_benchmark`), so they
produce identical artifacts, identical dashboard behavior, and identical trace-native output.
Pick based on where your pipeline already lives.

**YAML** — best when you're composing retobs's own adapters (BM25, dense, RRF fusion,
cross-encoder, Cohere, pgvector, Qdrant, HTTP) and want to sweep/compare multiple architectures
in one run:

```bash
retobs init --mode custom-jsonl --output my_experiment.yaml
retobs validate --config my_experiment.yaml
retobs run --config my_experiment.yaml
retobs serve --db .retobs/results.db
```

**Python SDK** — best when you already have retrieval code (a function, a class, a LangChain
retriever) and want to benchmark it with minimal ceremony:

```python
import retrieval_observatory as ro

@ro.retriever
def my_pipeline(query: str) -> list[str]:
    return my_vectordb.search(query, k=20)   # your existing retriever

report = ro.benchmark(my_pipeline, dataset="beir/scifact", max_queries=100)
report.show()     # per-stage metrics + failure diagnostics printed to stdout
report.serve()     # open the dashboard on this run
```

---

## Wiring retobs into a pipeline you already have

This is the common case: you have a working RAG pipeline and want retobs's diagnostics without
rewriting it. There are three levels, roughly in order of effort:

### 1. Wrap a single callable (fastest)

Any function `(query_text) -> list[str] | list[(id, score)] | list[Document]` works as-is:

```python
import retrieval_observatory as ro

def my_search(query: str) -> list[str]:
    return existing_rag.retrieve(query)   # zero changes to existing_rag

report = ro.benchmark(
    my_search,
    queries=[{"query_id": "q1", "text": "refund policy", "relevant_doc_ids": ["doc_17"]}],
    corpus={"doc_17": "Our refund policy allows returns within 30 days."},
    k=10,
)
report.show()
```

No labels yet? Synthesize a test set from your corpus (rule-based, no API key) or grade retrieved
docs on the fly with an LLM judge:

```python
testset = ro.generate_testset(corpus)                          # rule-based
report = ro.benchmark(my_search, dataset=testset)

report = ro.benchmark(my_search, queries=queries, corpus=corpus,  # zero ground truth
                       labels="llm-judge", judge="gemini")
```

### 2. Wrap a multi-stage pipeline (recover per-stage attribution)

Pass a list `[retriever, reranker, ...]` instead of one callable — retobs treats stage 0 as the
candidate generator and every later stage as a reranker over the prior stage's output, and
computes `candidate_miss` (gold doc never retrieved) vs `reranker_drop` (retrieved, then dropped)
per query:

```python
def retrieve(query: str) -> list[str]:
    return bm25_index.search(query, k=100)

def rerank(query: str, doc_ids: list[str]) -> list[str]:
    return my_cross_encoder.rerank(query, doc_ids, top_k=10)

report = ro.benchmark([retrieve, rerank], queries=queries, corpus=corpus)
```

If your existing pipeline already reports its own internal stages (e.g. it's a single opaque
callable that happens to return a `list[StageSnapshot]`), retobs passes it straight through —
you get stage attribution without splitting the callable at all.

### 3. Existing framework objects — zero rewriting

```python
# LangChain retriever
report = ro.benchmark(my_langchain_retriever, queries=queries, corpus=corpus)

# LlamaIndex retriever
report = ro.benchmark(my_llamaindex_retriever, queries=queries, corpus=corpus)
```

`ro.as_retriever()` auto-detects LangChain `BaseRetriever` / LlamaIndex retriever objects and
routes them through the matching adapter.

### 4. An existing HTTP retrieval service (no code changes at all)

```yaml
stages:
  my_service:
    type: adapter.http
    url: http://localhost:8080/retrieve
    config: {k: 100}
```

Request: `POST {"query": "...", "k": 100}` → expected response:
`{"documents": [{"id": "...", "text": "...", "score": 0.9}]}`. Field names are configurable
(`id_field`, `text_field`, `score_field`) if your service uses different keys.

### 5. Custom retrieval logic that doesn't fit any adapter

Use `adapter.import` (YAML) or a plain Python callable (SDK) — it's the escape hatch for anything
pipeline-specific (e.g. a post-rerank business-logic boost):

```yaml
stages:
  freshness_boost:
    type: adapter.import
    config:
      factory: my_module:build_recency_boost   # module:callable, or module.callable
      window_days: 120
```

```python
# my_module.py
from retrieval_observatory.types import Document, Query, RetrievalResult

class RecencyBoost:
    retriever_id = "freshness_boost"
    def rerank(self, query: Query, documents: list[Document]) -> RetrievalResult:
        ...  # your logic; return RetrievalResult(documents=..., latency_ms=..., retriever_id=self.retriever_id)

def build_recency_boost(corpus, stage_cfg, **kwargs):
    return RecencyBoost(), stage_cfg["config"].get("k", 10)
```

> **Naming gotcha:** retobs's trace-native layer infers each stage's operator type (`SOURCE`,
> `FUSE`, `RERANK`, `BOOST`, ...) from the stage's `retriever_id` string. Give custom stages a
> clear `retriever_id` (e.g. `freshness_boost`, not the default `adapter.import`) so the dashboard
> classifies and labels them correctly. Avoid names that accidentally contain another category's
> keyword — e.g. `recency_boost` contains `"recency"`, which is itself a reserved `SOURCE` keyword
> and would misclassify a `BOOST` stage as a `SOURCE`.

A full worked example combining all of this — a hybrid, multi-stage, custom-adapter pipeline on a
real custom dataset — lives in [`examples/complex_rag_demo/`](../examples/complex_rag_demo/).

---

## Hybrid, multi-stage, and complex pipelines

### Fan-in fusion (hybrid retrieval)

**SDK** — combine any ≥2 retrievers with Reciprocal Rank Fusion as stage 0:

```python
report = ro.benchmark([ro.fuse([bm25_retriever, dense_retriever]), reranker], queries=queries, corpus=corpus)
```

**YAML** — `adapter.rrf` fuses a list of sub-retrievers (BM25, dense, and/or HTTP only — custom
`adapter.import` retrievers can't be RRF sub-arms today):

```yaml
stages:
  hybrid:
    type: adapter.rrf
    retriever_id: hybrid_rrf
    config:
      rrf_k: 60
      retrievers:
        - type: adapter.bm25
          retriever_id: bm25
        - type: adapter.hf_biencoder
          retriever_id: dense
          config: {model: sentence-transformers/all-MiniLM-L6-v2}
```

Each arm becomes its own `SOURCE` operator span feeding a `FUSE` span in the trace — the dashboard
renders this as parallel arms merging into one node, and attribution can tell you which arm
contributed which unique relevant candidates.

### Comparing multiple architectures in one run

YAML `combinations` + `ablations: true` auto-generates every prefix/subset of a stage combo, so
you can compare (say) `hybrid` vs `hybrid+rerank` vs `hybrid+rerank+boost` side by side with real
significance testing, in one run:

```yaml
stages:
  hybrid: {type: adapter.rrf, config: {retrievers: [...]}}
  rerank: {type: adapter.hf_crossencoder, config: {model: cross-encoder/ms-marco-MiniLM-L-6-v2}}
  boost:  {type: adapter.import, config: {factory: my_module:build_recency_boost}}

combinations:
  include: [[hybrid, rerank, boost]]
  ablations: true   # generates [hybrid], [hybrid,rerank], [hybrid,boost], [hybrid,rerank,boost]
```

`retobs run` prints a **Stage Contribution** table for every adjacent pair with a paired bootstrap
delta and Benjamini-Hochberg-corrected significance — this is the "did adding this stage actually
help" answer, with a real p-value, not a guess.

### Complex production DAGs (gates, expansion, conditional lanes)

The YAML/SDK benchmark path is linear-plus-fusion only. If your production pipeline has intent
gates, conditional lanes, or graph-based expansion (thread siblings, entity links), instrument it
directly with `@observe`/`ro.init()` instead — see [Production tracing](#production-tracing-live-services)
below. That path supports the full 8-operator model (adds `GATE`, `EXPAND`, `FILTER`, `TRANSFORM`,
`BOOST`) and is how retobs represents pipelines it doesn't execute itself.

---

## Production tracing (live services)

Wire retobs into a running service so it traces real traffic — no ground truth required; you get
suspected-failure signals (`empty_candidates`, `latency_over_budget`, `high_churn`,
`low_confidence`) and, if you later attach qrels, real attribution.

### One-line setup

```python
import retrieval_observatory as ro

recorder = ro.init(service="search-api", db=".retobs/prod.db")   # V2 recorder by default
```

### FastAPI middleware

```python
from retrieval_observatory.tracing.integrations.fastapi import instrument_fastapi, get_trace

instrument_fastapi(app, recorder, pipeline_id="hybrid-search")

@app.get("/search")
async def search(q: str, request: Request):
    t = get_trace(request)          # None if this route/request is excluded or sampled out
    if t is None:
        return baseline_search(q)
    with t.stage("bm25") as s:
        s.results = bm25_ids(q)
    with t.stage("rerank") as s:
        s.results = rerank_ids(q, s.results)
    return s.results
```

### LangChain / LlamaIndex — zero manual stage wrapping

```python
from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallbackV2
cb = RetobsLangChainCallbackV2(recorder, pipeline_id="my-chain")
chain.invoke(query, config={"callbacks": [cb]})

from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexCallbackV2
Settings.callback_manager = CallbackManager([RetobsLlamaIndexCallbackV2(recorder, pipeline_id="my-index")])
```

Both are real `BaseCallbackHandler` subclasses (`on_retriever_start/end` → `SOURCE` span; a
LlamaIndex `RERANKING` event → `RERANK` span) — one line, no manual instrumentation.

### Manual, full-control instrumentation (gates, fusion, expansion, boosts)

For anything the automatic hooks don't cover — conditional gates, custom fan-in, graph expansion —
build `OperatorSpan`s directly and append them to the trace context:

```python
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan

async with recorder.trace(query_text, pipeline_id="kb-search", query_id=qid) as t:
    gate = OperatorSpan(
        op_id="gate_intent", op_type="GATE", op_name="intent_gate", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="NOT_REPLAYABLE", latency_ms=0.1,
        gate_values={"intent": intent},
    )
    t.add_span(gate)
    # ...append SOURCE / FUSE / EXPAND / FILTER / TRANSFORM / RERANK / BOOST spans similarly,
    # each with parent_ids pointing at the span(s) that fed it.
```

A complete worked example (intent gate → BM25+dense fan-in → thread-sibling graph expansion →
rerank → recency boost, on a real custom dataset) is in
[`examples/complex_rag_demo/run_demo.py`](../examples/complex_rag_demo/run_demo.py).

### Remote / centralized tracing

Push traces from an app that doesn't run `retobs serve` itself:

```python
from retrieval_observatory.tracing import HTTPSink
recorder = ro.init(service="prod-search")
recorder = TraceRecorderV2(service="prod-search", sink=HTTPSink("http://observatory.internal:4000/tracelens/traces"))
```

Or for full benchmark-run ingest (not just traces) from a remote process, use
`retrieval_observatory.sdk.remote.RemoteResultsClient` against
`POST /experiments/{name}/runs`, `/runs/{run_id}/results`, `/metrics`, `/finish`.

---

## The dashboard

```bash
retobs serve --db .retobs/results.db          # http://localhost:4000
retobs serve --db a.db --db b.db              # multiple databases, switchable in the UI
```

Four modes on the left rail:

| Mode | Question it answers |
|---|---|
| **Benchmarks** | What happened, and why — per-pipeline/per-stage metrics, architecture diagram, stage contribution significance, per-query failure labels, Pareto tradeoffs. |
| **Forge** | What failures haven't you found yet — corpus-specific synthetic stress queries (temporal confusion, alias mismatches). |
| **TraceLens** | What's happening in production — live trace feed, drift, hotspots (all suspected/heuristic, not measured Recall). |
| **Advisor** | What to do next — regression detection (paired bootstrap + BH correction), rule-based recommendations, reliability score. |

On a run's Benchmarks page:

- **Pipeline Architecture** (top of the page) — stage-by-stage diagram; hybrid pipelines render as
  parallel arms merging into an RRF fusion box.
- **Operator Attribution Grid** — segment × operator marginal contribution (which operator helped
  or hurt, per query segment), with replay-tier and low-power badges so nothing is overclaimed.
- **Operator Inspector** — per-operator detail: fire rate, replay tier, per-segment deltas.
- **Query Winner Table** / **Query Explorer** — per-query drill-down: which pipeline won, which
  failure label applied, predicted vs actual difficulty.
- **Stage Combination Matrix** / **Tradeoff Explorer** — compare all architectures in the run on
  quality, latency, and (if configured) cost.

`#/query/<query_id>` assembles the full cross-system lineage for one query: its Forge origin (if
any), every benchmark score, and any matching production trace.

---

## Metrics and attribution reference

**Ranking metrics** (`metrics/engine.py`): `recall@K`, `ndcg@K` (graded via `2^grade - 1`),
`precision@K`, `mrr`, `map`, `temporal_recall@K` (needs `timestamp_field`), latency
`p50`/`p95`/`p99`.

**Failure labels** (per query, `metrics/diagnostics.py`):

| Label | Meaning |
|---|---|
| `candidate_miss` | Gold doc never entered the candidate pool (stage 0 miss). |
| `reranker_drop` | Gold doc was retrieved, then dropped by a later stage. |
| `lexical_mismatch` / `semantic_mismatch` | One retrieval family succeeds where the other fails — the case for going hybrid. |
| `ranking_failure` | Retrieved, but ranked too low for the cutoff. |
| `unstable` | Inconsistent results across cache/re-runs. |

**Statistical significance**: paired bootstrap (1000 resamples) + Benjamini-Hochberg correction
across every metric comparison — used for stage attribution, Advisor regression checks, and
`assert_no_regression`. A result below the power threshold (`n_pairs < 20` by default) is flagged
`low_power`, not silently treated as "no effect."

**Operator attribution** (`tracing/attribution.py`, surfaced at
`GET /dbs/{db}/runs/{run}/operator-attribution?metric=recall&k=10`): for each operator and query
segment, compares "metric with the operator" vs "metric with the operator counterfactually
removed" across paired queries. Every result carries:

- `result_status`: `measured` (real, replay-supported comparison), `indeterminate` (operator isn't
  safely replayable — e.g. a non-deterministic dense retriever), or `not_applicable` (operator
  never fired in this segment).
- `replay_policy`: `EXACT` (deterministic operator, trust the number), `OBSERVED_ABLATION`
  (non-deterministic, e.g. an LLM reranker — trust direction, not precision), `NOT_REPLAYABLE`.
- `significant`: Benjamini-Hochberg-corrected, only set when `n_pairs` clears the power threshold.

This requires ground truth to be available for the run (qrels are persisted once per run when you
use `retobs run` / `ro.benchmark()`); a production-tracing-only run with no qrels attached will
honestly show `not_applicable` for every operator rather than a fabricated number.

---

## Datasets and qrels

Custom JSONL (`type: custom` in YAML, or `queries=`/`corpus=`/`qrels=` dicts in the SDK):

```jsonc
// corpus.jsonl
{"id": "doc_1", "title": "Optional title", "text": "Document text", "timestamp": "2025-01-01T00:00:00Z"}

// queries.jsonl
{"query_id": "q_1", "text": "query text", "relevant_doc_ids": ["doc_1"]}
{"query_id": "q_2", "text": "graded query", "relevant_doc_ids": {"doc_9": 2, "doc_3": 1}}
```

`relevant_doc_ids` accepts a binary list (all treated as grade 1) or a graded dict (arbitrary
integer grades; NDCG uses standard exponential gain, Recall/MAP/MRR treat any grade > 0 as
relevant). BEIR datasets work out of the box via `dataset: {type: beir, name: beir/scifact}` /
`ro.benchmark(pipeline, dataset="beir/scifact")`.

Label modes: `gold` (your qrels), `llm-judge` (grade retrieved docs on the fly, no ground truth
needed — `GOOGLE_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`), `pooled` (merge gold + judged).

---

## Full CLI reference

### Core

```bash
retobs init      --mode MODE --output PATH           # generate a starter config (+ sample dataset)
retobs validate  --config PATH                        # check a config before running it
retobs run       --config PATH [--no-cache] [--latency-budget-ms N]
retobs serve     --db PATH [--db PATH ...] [--port N] # dashboard (repeat --db for multiple)
retobs compare   RUN_A RUN_B --db PATH                # side-by-side comparison in the terminal
retobs inspect   RUN_ID --query QUERY_ID [--pipeline ID]
retobs demo      [--db PATH] [--full] [--keep-db]     # full 4-mode platform demo, no API keys
retobs quickstart [--db PATH] [--host H] [--port N]   # cold start, under 5 minutes
```

### Advisor (regressions, recommendations, CI gates)

```bash
retobs advisor check      --baseline RUN --candidate RUN --db PATH   # non-zero exit on regression
retobs advisor recommend  --run RUN_ID --db PATH
retobs advisor golden create --set NAME --queries queries.json
retobs advisor golden run    --set NAME --config experiment.yaml
retobs advisor golden list   --db PATH
```

### Forge (synthetic stress-test generation)

```bash
retobs forge scan --corpus corpus.jsonl [--scenario-types temporal,alias]     # no API key
retobs forge run  --corpus corpus.jsonl --output DIR/ \
                   [--query-types paraphrase,temporal,adversarial] \
                   [--llm-provider gemini|openai|anthropic] [--validate] [--db PATH]
retobs forge list --db PATH
```

### TraceLens (production trace inspection)

```bash
retobs tracelens demo  --service NAME --n 200 --db PATH   # seed synthetic traces
retobs tracelens stats --service NAME --db PATH            # summary: rates, latency, suspected failures
retobs tracelens purge --service NAME [--older-than-days N] --db PATH
```

### Query difficulty classifier

```bash
retobs classifier train   --dataset DATASET_NAME [--out PATH]
retobs classifier report  --dataset DATASET_NAME [--model PATH]
retobs classifier predict --model PATH --query "..."
```

Full flag-by-flag detail and YAML schema: [BREAKDOWN.md](../BREAKDOWN.md),
[YAML_GUIDE.md](../YAML_GUIDE.md).

---

## CI regression gating

```python
def test_no_retrieval_regression(retobs):        # pytest fixture, auto-registered on install
    baseline = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS, name="search")
    candidate = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS, name="search")
    retobs.assert_no_regression(candidate, baseline, metric="ndcg")
```

For YAML pipelines, use the Advisor CLI directly (non-zero exit on significant regression):

```bash
retobs run --config bench.yaml --no-cache
retobs advisor check --baseline "$GOLDEN_RUN" --candidate "$CANDIDATE" --db .retobs/results.db
```

Deeper detail (golden-run patterns, GitHub Actions template): [docs/informative/ci_gating.md](informative/ci_gating.md).

---

## Agent integration (REST + MCP)

Expose retobs to agents and other programs. Pipelines are passed as **config** (adapter specs),
not live Python objects.

- **Python:** `ro.run_from_config(cfg_dict)` runs a benchmark from an `ExperimentConfig`-shaped
  dict (the same seam the REST/MCP layers use) and returns a `BenchmarkReport`.
- **REST:** `retobs serve` exposes `POST /dbs/{db_id}/runs` (trigger), `.../status` (poll),
  `POST /dbs/{db_id}/compare-configs`, and `.../diagram` (diagram JSON). See
  [docs/integrations/api.md](integrations/api.md).
- **MCP:** `pip install 'retrieval-observatory[mcp]'` then `retobs mcp` exposes tools like
  `benchmark_config` and `benchmark_vs_baseline`. See [docs/integrations/mcp.md](integrations/mcp.md).
- **Read-only diagram:** `retobs diagram <run_id> -o out.html` writes a standalone HTML pipeline
  diagram with per-stage Recall/NDCG/latency and 95% bootstrap CIs.

---

## Troubleshooting

- **"No relevance judgments" warning** — queries with empty `relevant_doc_ids` are excluded from
  quality-metric means (not scored as 0); this is intentional so unlabeled queries don't silently
  deflate your numbers.
- **Operator Attribution Grid shows `not_applicable` everywhere** — the run has no qrels persisted
  (production-tracing-only runs, or a run from before qrel persistence existed). Re-run through
  `retobs run` / `ro.benchmark()`, which persists qrels automatically.
- **`adapter.hf_biencoder` / `adapter.hf_crossencoder` ImportError** — install the `dense` extra:
  `pip install "retrieval-observatory[dense]"`.
- **Filters silently ignored** — check the adapter's `supports_filters` flag; unsupported filter
  keys emit an explicit warning rather than failing silently. BM25, HF bi-encoder, pgvector, and
  Qdrant support equality filters; range filters (`>=`, `<=`, `in`) aren't supported yet.
- **Postgres store** — set `output.store: postgres` (YAML) with `RETOBS_POSTGRES_DSN`, or pass a
  Postgres DSN directly to `retobs serve --db`. Single-tenant, no auth, by design.
