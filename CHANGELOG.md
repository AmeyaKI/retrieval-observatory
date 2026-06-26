# Changelog

All notable changes to retrieval-observatory are documented here. Versions marked **[PyPI]** are published. Unreleased changes on `main` are at the top.

---

## [Unreleased]

Changes on `main` not yet published to PyPI.

### Fixed

- **[accuracy] Hybrid (fan-in) pipelines were mis-simulated.** The SDK modeled every pipeline as strictly linear (stage 0 = the sole candidate generator), so a hybrid expressed as `[retriever, fusion_reranker]` recorded only one arm's candidates in stage 0. A query whose relevant doc was found by the second arm and returned in the final results — a success — was incorrectly labeled `candidate_miss`. `metrics.diagnostics` now derives `candidate_miss` from the union of all stage snapshots and emits the informational `late_stage_recovery` label instead of inverting a successful query into a failure.
- **Production tracing 500'd out of the box.** `SQLiteStore` did not create its schema until `init_db()` was called manually, so the first traced request failed with `no such table: traces`. The store now creates its schema lazily on first write (`_ensure_schema` in `save_traces_batch`).
- `enrich`'s `low_confidence` default floor was `0.0`, which flagged every trace whose documents had unscored/zero scores. The default is now `None` (disabled unless a per-service floor is set).

### Added

- `ro.fuse([retriever_a, retriever_b, ...])` — express a hybrid as an accurate fan-in candidate-generation stage 0 (wraps the existing `RRFFusionAdapter`). A nested list in the pipeline (`ro.benchmark([[bm25, dense], rerank])`) is a convenience alias for the same thing; a flat list still means a sequence of stages. A fused stage is only valid at stage 0.
- `retobs.init(service=..., db=...)` — one-line production tracing setup that wires the store, sink, and recorder together (schema auto-created on first write).
- `t.stage("bm25", corpus=...)` as a context manager — auto-times the block and accepts bare document ids: `with t.stage("bm25") as s: s.results = ids`. The immediate form `t.stage(id, docs, latency_ms)` still works.
- FastAPI `instrument_fastapi` gained `exclude_paths` (defaults skip `/docs`, `/openapi.json`, `/redoc`, `/health`, `/favicon.ico`) and a `query_extractor` hook (default reads the `q` query parameter instead of recording the URL path).
- `types.StageSnapshot.arms` and `types.RetrievalResult.arm_results` — fused-stage arm snapshots are now first-class and persisted for dashboard topology rendering.

### Changed

- CLI `--db` options now also accept `--db-path` as an alias, matching the `db_path` constructor argument.
- `store.sqlite`/`store.postgres` — `raw_results` and `metric_scores` now persist `branch_id` rows for fused-stage arm branches with backward-compatible schema migrations.
- `metrics.engine` — branch-aware metric emission/aggregation now keeps fused-stage arm metrics separate via `branch_id`.
- `dashboard.api` — `/runs/{run_id}/overview` now returns `pipeline_topology` and stage contributions now include cross-pipeline, within-pipeline, and fused-arm ablation tiers.
- `dashboard/ui` — pipeline flow now renders fused fan-out/fan-in arm nodes, verdicts are tiered by comparison type, and module audit UX now surfaces truncation/default/threshold behaviors explicitly.

---

## [0.3.4] — 2026-06-24 [PyPI]

### Fixed

- Latent `None`-dereference in `BM25Adapter.retrieve` when the index is built lazily.
- `forge.labels.ground_truth`: widened the exception guard to `BaseException` so partial-failure gathers no longer raise during grading.
- Variable-shadowing bugs in `metrics.engine` and `datasets.custom` qrels loader.
- `QueryDifficultyModel.predict` label/driver selection no longer relies on a possibly-`None` dict key.

### Changed

- Removed dead module `datasets/timeqa.py` and unused imports/variables across the codebase.
- Added a `[tool.ruff]` lint configuration; added `ruff` and `types-PyYAML` to the `dev` extra.

---

## [0.3.3] — 2026-06-24 [PyPI]

### Changed

- Reverted PyPI distribution name from `retobs` back to **`retrieval-observatory`**. Install with `pip install retrieval-observatory`.
- Removed `retobs/` shim package. Public import is now `import retrieval_observatory as ro`.
- CLI command remains `retobs` (unchanged).
- Updated publish workflow, CI import checks, examples, and error messages to use `retrieval-observatory` extras syntax.

---

## [0.3.2] — 2026-06-24

### Added

- Public Python import path: `import retobs as ro` (shim package re-exporting the SDK).
- `retobs.tracing.integrations.*` shim modules for LangChain, LlamaIndex, and FastAPI tracing.

### Changed

- README, examples, and CI import checks use `retobs` as the documented package name.
- PyPI project URL and shields.io badge point at `https://pypi.org/project/retobs/`.

---

## [0.3.1] — 2026-06-24

### Changed

- PyPI distribution renamed from `retrieval-observatory` to `retobs` in `pyproject.toml`. Install with `pip install retobs`. (Publish to the `retobs` PyPI project requires trusted-publisher config; see [docs/PYPI_PUBLISH.md](docs/PYPI_PUBLISH.md).)

---

## [0.3.0] — 2026-06-23 [PyPI]

Adoption release: Python SDK (no YAML), native LangChain/LlamaIndex callbacks, `retobs quickstart`, and pytest CI gating.

### Week 1 — Adoption friction + framework integration

#### LangChain native callback integration

- `retrieval_observatory/tracing/integrations/langchain.py` — added `RetobsLangChainCallback`, a real `langchain_core.callbacks.base.BaseCallbackHandler` subclass. Hooks `on_chain_start/end/error` and `on_retriever_start/end` to emit `StageSnapshot`s automatically. Each root chain invocation produces one `RetrievalTrace`; multiple retrievers within one chain produce multiple stages without double-counting. Old `RetobsTraceHandler` kept for back-compat.
- `retrieval_observatory/tracing/recorder.py` — added `finish_trace_sync()`, a sync→async bridge (uses `loop.create_task` when a loop is running, `asyncio.run()` otherwise) shared by both framework callbacks.
- `examples/langchain_search/app.py` — new runnable example: FAISS vectorstore + `FakeEmbeddings`, no API keys, traces written to SQLite via one callback line.
- `tests/integration/test_langchain_callback.py` — 5 integration tests: 5 queries → 5 traces, correct stage counts, latency > 0, no double-counting, pipeline_id propagated. Uses `pytest.importorskip`.

#### LlamaIndex native callback integration

- `retrieval_observatory/tracing/integrations/llamaindex.py` — added `RetobsLlamaIndexCallback`, a real `llama_index.core.callbacks.base_handler.BaseCallbackHandler` subclass. Hooks `on_event_start/end` for `CBEventType.RETRIEVE` and `CBEventType.RERANKING` (verified against installed `llama-index-core` version). Flushes on `end_trace`. Old `RetobsLlamaIndexHandler` kept for back-compat.
- `examples/llamaindex_search/app.py` — new runnable example: `VectorStoreIndex` + `MockEmbedding`, no API keys.
- `tests/integration/test_llamaindex_callback.py` — 4 integration tests: trace count, retrieve stage present, pipeline_id, nodes become Documents. Uses `pytest.importorskip`.

#### Five-minute quickstart command

- `retrieval_observatory/cli.py` — added `retobs quickstart` command. Delegates to `_demo` (n_traces=50, no ablation) then launches the dashboard. Data generation completes in ~1.6s; total time to open dashboard under 5 minutes on a cold install with no API keys.
- `README.md` — updated top quickstart section: `retobs quickstart` is now the primary one-command path; `retobs demo` remains for the full platform demo.

#### FastAPI live-tracing demo hardened (task 1.4)

- `examples/fastapi_search/app.py` — added `?slow=1` query param (200ms sleep to trigger `latency_over_budget`), `RETOBS_LATENCY_BUDGET_MS` env var (default 50ms), score-filtering so zero-match queries produce `empty_candidates`, expanded corpus from 3 to 5 docs.
- `docs/verification/fastapi_live_trace_run.md` — literal transcript of the full 10-request verification run: commands, responses, and the resulting trace table showing 3× `empty_candidates`, 2× `latency_over_budget`, 5× no failures.

#### Error messages and failure modes (task 1.5)

- `retrieval_observatory/cli.py` — bad YAML in `retobs run` and `retobs validate` now prints a friendly one-line message + hint instead of a raw Python traceback.
- `retrieval_observatory/pipeline/factory.py` — `_build_hf_biencoder_adapter` and `_build_hf_crossencoder_adapter` now check for `sentence-transformers`/`faiss-cpu` at pipeline build time (fail fast) rather than at first `retrieve()` call. Message: `"Install with: pip install retobs[dense]"`.
- `retrieval_observatory/forge/generation/generator.py` — `_make_generator()` now checks for provider package at `ForgeGenerator.from_provider()` call time. Message: `"Install with: pip install retobs[llm-judge]"`.
- `retrieval_observatory/cli.py` — `_forge_run` now catches `ImportError` (not just `ValueError`) from `ForgeGenerator.from_provider()`.
- `docs/verification/error_messages_audit.md` — audit table of every triggered error class with before/after messages.

#### Docs (honesty pass)

- `README.md` — added "LangChain & LlamaIndex — zero-touch tracing" section under TraceLens; updated `suspected_failures` description to explicitly label all four signals as rule-based/heuristic.
- `BREAKDOWN.md` — integration table updated: `RetobsLangChainCallback` and `RetobsLlamaIndexCallback` listed as real `BaseCallbackHandler` subclasses (not "manual stage wrapping"); `predicted_difficulty` and `suspected_failures` both labeled **heuristic rule-based**.

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

