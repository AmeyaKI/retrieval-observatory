# Changelog

All notable changes to retrieval-observatory are documented here. Versions marked **[PyPI]** are published. Unreleased changes on `main` are at the top.

---

## [Unreleased] — main branch (post v0.2.0)

Changes since the v0.2.0 tag, not yet published to PyPI.

### Python SDK (code-first benchmarking — no YAML required)

- `retrieval_observatory/sdk/api.py` — new public `ro.benchmark()` function; `@ro.retriever` / `@ro.reranker` decorators; `ro.generate_testset()` for Forge-backed zero-label test set generation
- `retrieval_observatory/sdk/wrappers.py` — `FunctionRetriever` and `FunctionReranker` wrapping plain callables; normalizes three return shapes (`list[id]`, `list[(id,score)]`, `list[Document]`); `as_retriever()` auto-routes LangChain/LlamaIndex objects to existing adapters
- `retrieval_observatory/sdk/report.py` — `BenchmarkReport` with `.show()`, `.to_pandas()`, `.serve()`, `.compare(baseline)`, `.assert_no_regression(baseline, metric=)`
- `retrieval_observatory/datasets/inmemory.py` — `InMemoryDataset` for list/dict BYO queries, corpus, and qrels; no file I/O required
- `retrieval_observatory/__init__.py` — exports `benchmark`, `retriever`, `reranker`, `generate_testset`, `Query`, `Document`, `BenchmarkReport`

### Shared benchmark executor

- `retrieval_observatory/runner/execute.py` — `execute_benchmark()` and `BenchmarkArtifacts`; both `cli._run` and `sdk/api.benchmark()` route through this function, guaranteeing identical artifacts and query lineage regardless of entry point
- `cli.py` — refactored `_run` to delegate to `execute_benchmark()`; moved `_build_llm_judged_qrels`, `_merge_qrels`, `_annotate_query_difficulty` from `cli.py` to `execute.py`

### Phase 2 — per-stage snapshots from a monolith

- `pipeline/single.py` — `SingleStagePipeline.run()` now detects if the wrapped callable returns a `PipelineResult` or `list[StageSnapshot]` and passes it through unchanged; `_as_pipeline_result()` helper added
- Enables wrapping an opaque production pipeline that reports its own internal stages; per-stage attribution and `reranker_drop` diagnostics work even for a single callable

### Phase 3 — zero-label evaluation

- `ro.generate_testset(corpus)` — wraps `ForgeEngine` + `StressTestSuite` into an `InMemoryDataset` using rule-based detectors (no API key required)
- `ro.benchmark(..., labels="llm-judge", judge=...)` — surfaces the existing LLM judge path through the SDK

### Phase 4 — pytest CI gate

- `retrieval_observatory/pytest_plugin.py` — `retobs` pytest fixture with `.run()` and `.assert_no_regression()`; registered via `pytest11` entry point in `pyproject.toml`
- `BenchmarkReport.assert_no_regression(baseline, *, metric, latency_regression_pct)` — raises `AssertionError` with formatted findings on statistically significant regression; uses paired bootstrap + Benjamini-Hochberg

### Examples & docs

- `examples/demo_phases.py` — walkthrough of SDK Phases 1–3 (single-stage, multi-stage, monolith, synthetic testset)
- `examples/sdk_quickstart.py` — annotated quickstart with `@ro.retriever` and multi-stage form
- `docs/ci_gating.md` — pytest fixture usage, golden-run pattern, CLI alternative
- `README.md` — new "benchmark your pipeline in Python (no YAML)" section; zero-label and pytest-gate snippets added
- `PLAN.md` — full adoption roadmap (Phases 0–4 committed; Phases 5–7 demand-gated)
- `FUTURE_EDITS.md` — Phases 5–7 in Problem→Fix→Implementation format

### Tests

- `tests/unit/test_sdk.py` (new) — 9 tests: wrapper normalization, async, in-memory metrics, lineage written, multi-stage per-stage snapshots
- `tests/unit/test_multi_snapshot.py` (new) — monolith passthrough: stage0 recall=1.0, stage1 recall=0.0 (reranker_drop)
- `tests/unit/test_zero_label.py` (new) — LLM judge path (mocked) + real Forge testset generation
- `tests/unit/test_pytest_gate.py` (new) — fixture passes when stable; raises on degraded retriever (10 queries for bootstrap power)
- `tests/integration/test_end_to_end.py` — updated import: `_annotate_query_difficulty` now from `runner/execute.py`

---

## [0.2.0] — 2026-06-17 [PyPI]

Major milestone: the four-mode **retrieval reliability platform**. Forge, TraceLens, and Advisor shipped alongside a rebuilt dashboard.

### Platform demo

- `retobs demo` — one command builds the full four-mode showcase: Forge scan → baseline BM25 (k=20) vs degraded BM25 (k=1) → TraceLens traces with drift/hotspots → Advisor regression check → dashboard URLs
- `retobs demo --full` — additional multi-stage BM25 + rerank ablation benchmark
- `retobs demo --keep-db` — appends to existing demo database instead of wiping
- `dashboard/demo_context.py` + `GET /demo/context` — dashboard auto-configuration from demo artifacts
- Demo manifest (`demo_manifest.json`) carries baseline/degraded run IDs and a sample query ID for lineage

### Dashboard — four-mode lifecycle rail

- `AppShell` + `ModeRail` + URL-hash routing replacing the single-mode layout
- Mode rail: Benchmarks (indigo) / Forge (amber) / TraceLens (teal) / Advisor (violet)
- `ComparePanel.tsx` — rewritten: win/loss cell highlighting, summary banner, metrics grouped by type (quality/latency/other), human-readable run labels
- `RunsSidebar.tsx` — selection count badge, contextual help text for 0/1/2+ selected states
- `DashboardGuide.tsx` — two-column layout explaining chart navigation and multi-architecture vs ablation runs
- `RecallCurve.tsx`, `RecallFunnel.tsx`, `LatencyChart.tsx` — `ChartZoomControls` with +/- buttons; zoom in/out helpers in `useChartZoom.ts`
- `RunDetail.tsx` — all section headers have subtitle descriptions; Tradeoff Explorer sliders have better labels
- `App.tsx` — improved empty state with onboarding copy
- `ForgeWorkspace` — new: dataset list, dataset detail (overview + label-trust banner, scenario explorer, query browser, stress test results by scenario/difficulty)
- `TraceLensWorkspace` — new: trace feed, distribution, drift, hotspots, clusters (7 views)
- `StressTestResults.tsx` — self-gated; reuses `/metrics/by-segment` to show Forge run breakdown by scenario type and difficulty

### Forge

- `retrieval_observatory/forge/` — full subpackage: types, scenarios, generation, labels, stress, datasets
- Scenario detectors: `temporal.py` (regex-based, no ML), `alias.py`, `entity_ambiguity.py` (heuristic)
- Rule-based query generators: temporal, paraphrase, comparison, constraint, long_tail
- LLM query generation wrapping Gemini/OpenAI/Anthropic judge pattern
- Extractive qrel builder + optional LLM validation (`forge/labels/ground_truth.py`)
- Difficulty scoring: heuristics + trained-model fallback (`forge/labels/difficulty.py`)
- `StressTestSuite` with difficulty/scenario/type filtering (`forge/stress/suite.py`)
- BEIR + custom JSONL export with `forge_metadata.json` (`forge/datasets/exporter.py`)
- CLI: `retobs forge scan`, `retobs forge run`, `retobs forge list`
- SQLite tables: `forge_datasets`, `forge_scenarios`, `forge_queries`
- FastAPI routes: `/forge/datasets`, `/forge/datasets/{id}`, `/forge/datasets/{id}/scenarios`, `/forge/datasets/{id}/queries`, `/forge/datasets/{id}/runs`
- `pyproject.toml`: `forge` optional extra (LLM SDKs)
- Backend fix: `_forge_run` now persists datasets to the store with `--db`; new `save_forge_queries` / `get_forge_queries` store methods; `validation_coverage` field

### TraceLens

- `retrieval_observatory/tracing/` — new subpackage
- `tracing/types.py` — `RetrievalTrace` (reuses `StageSnapshot` / `Document` from `types.py`, `as_pipeline_result()` helper)
- `tracing/recorder.py` — `TraceRecorder` SDK: async context manager, imperative `start_trace()`/`finish_trace()`
- `tracing/sink.py` — `StoreSink` (SQLite/Postgres), `HTTPSink` (remote push), `MemorySink` (tests)
- `tracing/enrich.py` — enriches traces at ingest: `predicted_difficulty` + label-free proxy failures (`empty_candidates`, `low_confidence`, `high_churn`, `latency_over_budget`)
- `tracing/monitor/distribution.py` — difficulty and failure label histograms
- `tracing/monitor/drift.py` — PSI + KS test comparing baseline vs recent window
- `tracing/monitor/hotspots.py` — failure pattern frequency ranking
- `tracing/monitor/cluster.py` — text clustering of similar failing queries
- `tracing/integrations/fastapi.py` — `instrument_fastapi()` middleware + `get_trace()` helper
- `tracing/integrations/langchain.py`, `tracing/integrations/llamaindex.py` — manual instrumentation helpers
- SQLite tables: `traces`, `trace_stages`
- FastAPI: `tracelens_router` (ingest + read + monitor endpoints)
- CLI: `retobs tracelens demo|stats|purge`
- `examples/fastapi_search` defaults to `StoreSink` writing to the demo DB path

### Advisor

- `advisor/regression.py` — baseline vs candidate comparison; BH-adjusted q-values; non-zero CLI exit on regression
- `advisor/recommend.py` — rule-based recommendations from diagnostics + optional TraceLens hotspot signals; composite reliability score (named components)
- `advisor/golden.py` — named query set primitives for long-term CI gates
- `advisor/trends.py` — reliability score snapshots and trend list
- CLI: `retobs advisor check|recommend|golden create|golden run|golden list`
- Dashboard: Advisor workspace with regression center, recommendations, reliability score, trend list

### Docs & CI

- `README.md` — rewritten as reliability-platform-first; `retobs demo` tour, four-mode table, TraceLens, Advisor, benchmark results table
- `BREAKDOWN.md` — technical reference (this file's predecessor)
- `RESULTS.md` — full benchmark results: NFCorpus, SciFact, FiQA (1,271 queries); Pareto analysis
- `results/BENCHMARK_ANALYSIS.md` — deep-dive Pareto analysis and statistical methodology
- `YAML_GUIDE.md` — six copy-paste YAML templates + LLM prompt for generating configs
- `.github/workflows/retrieval-ci.yml` — golden regression gate on PRs
- `pyproject.toml` — added `forge`, `tracelens`, `cohere`, `pgvector`, `llm-judge` optional extras

---

## [0.1.2] — 2026-06-05 [PyPI]

Patch release to fix PyPI publish pipeline.

- Fixed CI smoke test: install local wheel, avoid TestPyPI typosquats during smoke verification
- No functional changes from v0.1.1

---

## [0.1.1] — 2026-06-05 [PyPI]

Patch release to fix publish pipeline.

- Fixed TestPyPI smoke install index order
- Bumped version to retry PyPI release

---

## [0.1.0] — 2026-06-04 [PyPI]

Initial public release. Multi-stage retrieval benchmarking with a React dashboard.

### Core benchmarking

- YAML-configured multi-stage retrieval pipelines: `combinations` + `ablations: true` for prefix pipeline generation
- Per-stage `StageSnapshot` model: doc IDs, scores, latency per stage per query
- `MetricsEngine`: recall@K, NDCG@K, MRR, MAP, temporal_recall@K, latency percentiles
- Per-query failure labels: `candidate_miss`, `reranker_drop`, `late_stage_drop`, `lexical_mismatch`, `semantic_mismatch`, `ranking_failure`
- Stage attribution: paired bootstrap + Benjamini-Hochberg correction comparing prefix pipelines
- Pareto frontier analysis (quality vs latency vs cost)
- Stage-level result cache (hash of config + upstream docs + query ID)
- `run_manifests` table: config hash, dataset fingerprint, package versions, git commit

### Adapters

- `adapter.bm25` — rank-bm25
- `adapter.hf_biencoder` — sentence-transformers + FAISS (dense retrieval)
- `adapter.hf_crossencoder` — cross-encoder reranker
- `adapter.rrf` — Reciprocal Rank Fusion
- `adapter.cohere_rerank` — Cohere Rerank API
- `adapter.http` — any REST retrieval endpoint
- `adapter.import` — custom Python factory
- `adapter.pgvector` — pgvector-backed Postgres retrieval
- LangChain adapter (`adapters/langchain_adapter.py`)
- LlamaIndex adapter (`adapters/llamaindex_adapter.py`)

### Datasets

- BEIR dataset integration (via `beir` library)
- Custom JSONL dataset (queries + corpus + qrels)
- TimeQA dataset (temporal recall metrics)
- LLM-assisted relevance judging: `gold`, `llm_judge`, `pooled_llm_judge` modes
- Dataset validation with schema checks

### Query difficulty classifier

- `classifier/` — logistic regression on diagnostic features from past runs
- `retobs classifier train|report|predict` CLI
- Auto-applied when a matching model exists; difficulty buckets stored in `query_diagnostics`

### Dashboard

- React SPA served by FastAPI at `retobs serve`
- Runs list, metrics table, stage attribution chart
- Query explorer with per-query failure labels
- Pareto tradeoff explorer with quality/latency/cost sliders
- `RecallCurve`, `RecallFunnel`, `LatencyChart` with pinch-to-zoom
- `ComparePanel` for side-by-side run comparison
- Multi-DB support: `retobs serve --db a.db --db b.db`

### Storage

- SQLite store (default): `runs`, `run_manifests`, `raw_results`, `metric_scores`, `query_diagnostics`, `run_queries`, `result_cache`, `golden_sets`
- Postgres store (`store/postgres.py`): same `BaseStore` interface (core benchmark tables)

### CLI

- `retobs init`, `retobs validate`, `retobs run`, `retobs serve`, `retobs compare`, `retobs inspect`, `retobs demo`
- `retobs advisor check|recommend|golden`
- `retobs classifier train|report|predict`

### Benchmark results (v0.1.2 case study)

- NFCorpus: BM25 NDCG@10=0.264, Dense NDCG@10=0.310 (+17.6%)
- SciFact: BM25 NDCG@10=0.544, Dense NDCG@10=0.640 (+17.7%)
- FiQA: BM25 NDCG@10=0.159, Dense NDCG@10=0.369 (+132%)
- Dense (`all-MiniLM-L6-v2`) is Pareto-optimal on SciFact and FiQA at 133–228× lower latency than cross-encoder reranking

