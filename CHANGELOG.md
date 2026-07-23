# Changelog

All notable changes to retrieval-observatory are documented here. Versions marked **[PyPI]** are published. Unreleased changes on `main` are at the top.

---

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [0.5.4] — 2026-07-23 [PyPI]

Publish workflow hardening after 0.5.3 uploaded successfully but post-upload PyPI JSON verification raced a 404.

### Fixed

- `.github/workflows/publish.yml` — retry TestPyPI/PyPI JSON metadata fetches until the index is visible; allow idempotent PyPI re-upload with `skip-existing`.

## [0.5.3] — 2026-07-23 [PyPI]

Local release-policy decisions, claim-scoped evidence readiness, and the Candidate Lineage Explorer — plus architecture docs aligned to the current integrate → evaluate → compare → inspect surface.

### Added

- `release/policy.py` and `release/assessment.py` — support exact one-to-one reviewed stage mappings for semantically aligned lineage diffs across renamed topology nodes.
- Candidate Lineage Explorer — add branch, stage, outcome, evidence, and source filters; aggregate route widths; and complete passport rank, score, exit, and source evidence.
- `dashboard/api.py` and Compare UI — accept an explicit local policy path and render the canonical configured-policy decision without browser-side status logic.
- `release/statistics.py` and dashboard release cards — bind each aggregate and declared-slice guard to its own most affected paired query IDs.
- `store/base.py`, `store/sqlite.py`, and `store/postgres.py` — support time-window-bounded instrumentation-health reads for release evidence profiles.
- `tracing/model.py` and `release/evidence.py` — version candidate lineage independently of the trace envelope and measure document-revision identity coverage for safe run diffs.
- `release/policy.py` and `release/assessment.py` — allow policies to make declared lineage-diagnosis readiness explicitly promotion-critical.
- `release/policy.py` and `release/readiness.py` — add bounded local release-policy and claim-scoped evidence-readiness contracts.
- `tracing/model.py`, `tracing/candidates.py`, and `tracing/lineage_contract.py` — add backward-compatible candidate identity, DAG parentage, and recorded-versus-inferred decision evidence.
- `store/base.py`, `store/sqlite.py`, and `store/postgres.py` — support indexed run-and-query-scoped trace retrieval across both storage backends.
- `release/evidence.py` and `runner/execute.py` — persist run-window-scoped release identity, lineage coverage, topology, and telemetry evidence in completed manifests.
- `release/assessment.py` and `metrics/comparison.py` — assess promotion, evaluation, lineage, diff, and production-trace evidence independently with stable findings.
- `release/statistics.py`, `release/slices.py`, and `release/decision.py` — add paired effect intervals, exact declared-slice guards, and PASS/HOLD/BLOCK/FAIL decision precedence.
- `sdk/report.py`, `sdk/api.py`, `cli.py`, and `mcp/server.py` — expose one schema-versioned release decision artifact with local policy inputs and canonical CI exit modes.
- `integrations/verify.py` and `tracing/adapters/otel.py` — preflight local release-policy lineage capture and map explicit OpenTelemetry retrieval attributes without an SDK dependency.
- `tracing/lineage.py` and `tracing/lineage_accounting.py` — derive immutable candidate routes, evidence-aware operational outcomes, and stage loss accounting from recorded trace lineage.
- `dashboard/api.py`, `dashboard/analysis_api.py`, and `dashboard/ui/src/api.ts` — expose query-scoped lineage graphs, candidate passports, accounting, and claim readiness with privacy-safe compatibility aliases.
- `dashboard` Compare and Candidate Lineage Explorer — present canonical release decisions before raw metrics and replace confusion labels with static, evidence-aware candidate routes, outcomes, accounting, passports, and optional recorded replay.
- `tracing/lineage_diff.py` and dashboard query diff — compare stable candidate identities only when query, document revision, and topology evidence align; otherwise preserve side-by-side recorded paths with blocked readiness.
- `docs/guides`, `examples/ci`, and release-evidence contracts — publish and prove the local/CI release-decision and candidate-lineage workflow with deterministic, no-secret fixtures.

### Changed

- `docs/ARCHITECTURE.md` and `docs/CONCEPTS.md` — document the current evidence path, release/lineage contracts, claim-scoped readiness, and public task surface.
- `contracts/public_surface.json` — include Architecture and the release/lineage guides in the release-gated documentation set.

### Fixed

- `dashboard/api.py` candidate-lineage diff — block ambiguous multi-trace pairing and preserve every unpaired recorded graph instead of selecting an arbitrary trace.
- `pipeline/dag.py` and `tracing/model.py` — preserve native operator drop reasons as recorded decision evidence and persist explicit branch identity on spans.

### Removed

## [0.5.1] — 2026-07-17 [PyPI]

Dashboard single-run diagnosis polish, Production API client fix, `evaluate --config` repair, and the remaining audit-remediation surface that landed after 0.5.0.

### Added

- `dashboard` query diagnosis — TP/FP/FN/TN seen-candidate table + animated stage flowchart on Query detail; Queries list prioritizes query text.
- `docs/guides/getting-started.md` — SciFact hybrid <10 min multi-stage demo via `retobs evaluate --config` (not removed `retobs run`).
- `dashboard` candidate-flow diagnosis — `GET .../candidate-journeys` joins qrels + drop history; Query detail shows a per-pipeline path simulator and miss overview table.
- `tracing/model.py` — define one service-scoped trace identity for production and evaluation with parent-grouped candidate evidence.
- `integrations/model.py` — add deterministic plan, manifest, phase-specific result, check, patch, and verification contracts.
- `diagnostics/model.py` — add versioned evidence contracts for supported, limited, unavailable, and not-observed retrieval findings.
- `contracts/public_surface.json` and `scripts/check_public_surface.py` — make supported CLI, MCP, SDK, documentation, extras, and integration tiers release-gated contracts.
- `contracts/forbidden_vocabulary.json`, `scripts/check_public_vocabulary.py`, and `scripts/check_markdown_links.py` — reject removed public vocabulary and broken documentation anchors in CI.
- `tests/external_projects/` — add self-contained callable, FastAPI, LangChain, and LlamaIndex integration fixtures with declared topology and output contracts.
- `integrations/` — preserve fixture-declared service identity and expose verification capability and telemetry-health evidence.
- `scripts/smoke_external_project.py` and `tests/release/` — prove plan/apply/verify, production-without-run, telemetry containment, and import isolation against installed wheels.
- `cli.py` — let `integrate --phase apply --plan` consume the reviewed plan emitted by `--phase plan --output`.
- `sdk/observe.py` — omit unfired branch parents from candidate evidence so optional routes cannot alter host behavior.
- `tracing/model.py` — calculate critical paths without requiring parents from unfired branches.
- `sdk/observe.py` — omit skipped branch parents from stored trace topology as well as candidate groups.
- `integrations/planner.py` — discover explicit `source` functions as canonical source operators.
- `scripts/smoke_wheel.py` and `tests/release/` — add installed-wheel evidence for public surfaces, evaluation, production traces, loopback serving, and bundled assets.
- `.github/workflows/release-candidate.yml` — build one checksummed release artifact and test it across Python, external fixtures, stores, and dashboard/browser gates.
- `scripts/verify_release_artifact.py` and publish workflow — promote only the checksummed release-candidate wheel and sdist through TestPyPI and PyPI.
- `scripts/generate_release_evidence.py` and release-candidate CI — publish one digest-bound, machine-verifiable release-evidence JSON and Markdown artifact for every required gate.

### Changed

- `dashboard` BenchmarksWorkspace / RunsSidebar — auto-select newest run; refetch on focus; click selects one run (checkbox/modifier for Compare).
- `dashboard` ModeRail — demote Compare below primary single-run modes.
- `dashboard` PipelineDagView / dagLayout — taller content-aware nodes, compact single-line metrics, no clipped foreignObject text.
- `examples/` and bundled SciFact config — rename active quickstart paths to evaluation-oriented names.
- CI and retrieval comparison workflows — separate source PR gates from wheel-only release-candidate evidence and record tested wheel digests.
- Public documentation and package metadata — center the installed-wheel `integrate plan/apply/verify` workflow, active task vocabulary, evidence limits, and loopback safety boundary.
- `pipeline/executors.py` and `tracing/integrations/operator_registry.py` — add typed DAG execution and manifest-stable framework operator identity.
- `tracing/config.py`, `serialization.py`, and `exporters.py` — add bounded, redacted, retry-aware trace capture with measured health.
- `diagnostics/` — add branch-aware candidate histories and versioned identity, routing, transition-loss, truncation, and final-ranking rules.
- `store/` — persist ordered typed diagnostic findings with indexed evidence metadata in SQLite and PostgreSQL.
- `integrations/` — add one deterministic plan/apply/verify workflow with concrete source patches, stale-plan protection, reversal metadata, and observed-trace readiness checks.
- `dashboard/ui/src/context/DashboardContext.tsx` — add URL-backed database, service, run, time-window, cohort, and filter context.
- `analysis/` and `dashboard/analysis_api.py` — add cohort-scoped router, branch, score, latency, corpus, ground-truth, instrumentation, baseline, regression-check, and local-alert analysis products using one evidence contract.
- `store/sqlite.py` and `store/postgres.py` — add versioned cohort, corpus snapshot, judgment, baseline, check, and alert persistence.
- `config/operators.py` — replace generic DAG nodes with validated operator-specific graph specifications.
- `tracing/`, `store/`, `dashboard/api.py` — isolate trace export behind a bounded queue and expose measured capture health.
- `cli.py` — bind `retobs serve` to `127.0.0.1` by default and warn on remote exposure.
- `store/`, `runner/`, `metrics/`, and `dashboard/api.py` — use the sole unified trace record for production and evaluation workflows.
- `runner/execute.py`, `evidence/query.py`, `advisor/recommend.py`, and `dashboard/api.py` — consume persisted trace-native findings without pipeline-name diagnosis.
- `dashboard/api.py` and Production/Test Set UI — paginate traces, topology variants, and Test Set queries; summarize production matches and separate Compare decision dimensions.
- `dashboard/ui/src/analysis/` — expose shareable, cohort-aware ready/partial/unavailable analysis views without rendering unsupported claims.
- `cli.py` and `mcp/server.py` — expose `integrate`/`integrate_project` as the sole integration workflow.

### Fixed

- `.github/workflows/publish.yml` — stage only wheel/sdist into `packages/` so `SHA256SUMS` is not uploaded as a distribution.
- `cli.py` `evaluate --config` — import `run_from_config` from `sdk` (was `ro.run_from_config`, missing on package root).
- `dashboard/ui/src/api.ts` — Production TraceLens clients call `/production/*` with `service_id` (was `/tracelens/*` → SPA HTML → JSON parse error).
- `store/postgres.py` — deserialize JSONB trace payloads returned as strings before reconstructing traces.
- `tracing/sink.py` and `scripts/generate_release_evidence.py` — retain telemetry and release-evidence behavior on Python 3.10.
- `cli.py` — create requested integration-plan output directories and resolve project-root callable modules for the documented installed-wheel commands.

### Removed

- `tracing/model_v2.py`, `tracing/types.py`, and `tracing/lift.py` — remove split trace models and lift compatibility paths.
- `integrations/wire.py` and legacy integration CLI/MCP entrypoints — remove competing setup, bootstrap, plan, wire, and standalone verify paths.
- `retrieval_observatory/cli.py` — remove deprecated `run`, `wire`, `doctor`, `inspect`, `quickstart`, `forge`, `tracelens`, and `advisor` command surfaces.
- `retrieval_observatory/mcp/server.py` — remove wiring, bootstrap, benchmark-descriptor, Pareto, recommendation, and diagram aliases in favor of the task-oriented MCP contract.
- `retrieval_observatory/__init__.py` and `retrieval_observatory/tracing/__init__.py` — remove legacy benchmark, snapshot, recorder, and helper exports from the supported SDK.
- `docs/MIGRATION.md` — remove the compatibility-window guide after the beta clean break.

## [0.5.0] — 2026-07-14 [PyPI]

Major product revamp: one callable-first retrieval debugging loop replaces the old four-module surface (Benchmarks / Forge / TraceLens / Advisor). CLI, SDK, MCP, dashboard, and CI now share the same evaluate → compare → inspect-query vocabulary, evidence contracts, and validity-gated statistics.

### Added

- Canonical report + QueryEvidence contracts shared by CLI, SDK, MCP, dashboard, and CI artifacts (verdict, evidence health, provenance, next action).
- Manifest schema V3 with separate query/corpus/qrel fingerprints, content hashes, execution seed, and environment metadata for reproducible comparisons.
- PipelineGraphV2 projections (run-union and exact-trace) with concurrent DAG siblings and distinct wall-clock / critical-path / operator-sum latency.
- Candidate lineage and first-loss debugging: immutable source-lane origins, per-operator additions/drops, candidate-flow views, and recorded-vs-execution replay classification.
- Production findings and Test Sets as first-class surfaces (versioned summaries, generation/label provenance without calling unvalidated labels gold).
- Integration wiring path: detect → plan → wire/verify for plain Python, HTTP, FastAPI, LangChain, and LlamaIndex; duck-typed adapters for Haystack, DSPy, and OpenAI Agents.
- Task-oriented public docs (Start, Workflow, Concepts, Reference, Evidence & trust, Integrations, Architecture, Migration) plus security/conduct policies.
- Release/CI hardening: Ruff, lockfile UI installs, Markdown link checks, browser WCAG workflow, framework smoke tiers, wheel smoke, versioned demo assets.

### Changed

- Product IA — Home / Runs / Compare / Queries / Production / Test Sets; legacy Benchmarks/Forge/TraceLens/Advisor routes and labels migrate or alias with v1.0 retirement warnings.
- `retobs compare` and dashboard Compare — one validity-gated, BH-corrected, power- and effect-thresholded baseline/candidate decision; profile noise no longer gates regressions.
- Dashboard run/query UX — verdict-led overview, query debugger with qrels/provenance/evidence health, lazy-loaded workspaces, bundle budgets, and shared status semantics.
- `retobs demo` — deterministic Test Set → regression → query cause → validation story used by CI golden-check and README media.
- Store + diagnostics — structured diagnostic evidence, paginated V2 traces, and one SQLite/PostgreSQL store contract.

### Fixed

- `dashboard/ui/src/components/RunQueryDetailPage.tsx` — tolerate unified trace timing, input, and diagnostic evidence shapes in query drill-downs.
- Partial traces retained on operator error/timeout/cancellation instead of silent drop.
- Ambiguous multi-db dashboard evidence routes now require explicit database scope.
- Integration verify fails closed on zero runs or required-check failures.
- Packaging/CI edge cases: bytecode excluded from wheels; release metadata parseable on Python 3.10; publish smoke installs the wheel outside the source checkout so gitignored `ui/dist` cannot shadow site-packages.

### Removed

- Four-product framing as the primary UX (engines remain under Test Sets / Production / Findings).
- Heuristic diagram topology path in favor of trace-native PipelineGraphV2.
- Local-only contributor notes from the published tree (kept out of the package/docs release surface).

## [0.4.2] — 2026-07-06

### Added

- `PipelineGraph` contract + `/runs/{id}/pipeline-graph` — canonical DAG JSON with bootstrap CIs; `PipelineDagView.tsx` (dagre-free layered SVG) replaces `StagePipelineFlow`; honest empty state (no `fallbackTopology`).
- `runner/manifest.py` — `schema_version`, `stage_labels`, `duplicate_ablation_stages` from resolved config (retires float-equality ablation heuristics).
- `integrations/registry.py` + MCP `describe_integration` / `verify_integration`; CLI `retobs integrate`, `retobs doctor`.
- `docs/integrations/AGENT_QUICKSTART.md` — numbered MCP journeys for benchmark vs instrument paths.
- `examples/hybrid_fiqa_demo/` — hybrid RRF+rerk BEIR configs (FiQA, SciFact, NFCorpus) + `run_demo.sh`.
- `examples/hybrid_fiqa_demo/config_scifact_graph.yaml` — declarative `graphs:` DAG config with two genuine merge points (bm25∥dense → RRF fuse → rerank → second RRF re-fusion with the raw bm25 arm); verified end-to-end against real BEIR SciFact (run `fdc717bd`) — `/pipeline-graph` renders both fusion nodes as `MERGE` with correct `fan_in` edges, Pareto/tradeoff correctly uses end-to-end P50 (~1219ms) rather than any single node's stage-local latency.
- Dashboard vitest harness + `dagLayout.test.ts` (pure layout fidelity for 2-arm + FUSE + RERANK fixture).
- `RunSectionNav` + Benchmarks deep links `#/benchmarks/run/{id}/{section}`; sticky in-page IA (Overview · Architecture · Quality · Tradeoffs · Queries).
- `RunManifestPanel` — dataset fingerprint, query count, config hash on run overview.

### Changed

- `dashboard/api.py` `_extract_final_stage_metrics` — Pareto/tradeoff inputs use end-to-end P50/P95 (`stage_index=-1`); `/pareto-frontier` emits NDCG CI bounds + omitted-pipeline note.
- `TradeoffScatter.tsx` — NDCG CI whiskers, end-to-end latency axis label, frontier-overlap highlighting.
- `RecallFunnel.tsx` / `ComparePanel.tsx` / `VerdictCard.tsx` — bootstrap CIs surfaced; verdict medals CI-aware; e2e latency on ranking cards.
- `LatencyChart.tsx` / `pipelineStages.ts` — stage labels from manifest, not `__`-split pipeline-id parsing.
- `mcp/server.py` — `benchmark_config` normalizes legacy descriptor shape; `benchmark_pipeline_descriptor` deprecated in-tool; `retobs-mcp.yaml` drops unused `pipeline_name`.
- `config/discovery.py` — hard-error on `adapter.qdrant` + `embedding_fn` in YAML.

### Removed

- `StagePipelineFlow.tsx` — superseded by `PipelineDagView`.
- `OperatorDagView.tsx` — superseded by `PipelineDagView` (benchmark + trace-native graphs share one contract).
- Root planning clutter moved out of the published tree into local archive.

- `retrieval_observatory.sdk.run_from_config(config: dict)` — run a benchmark from an
`ExperimentConfig`-shaped dict (adapter specs, not live Python objects); the shared seam REST and
MCP both call. Exported at top level as `retrieval_observatory.run_from_config`.
- REST endpoints in `dashboard/api.py`: `POST /dbs/{db_id}/runs` (trigger a run; background job or
`wait=true` bounded-sync), `GET /dbs/{db_id}/runs/{run_id}/status`, `POST /dbs/{db_id}/compare-configs`,
and `GET /dbs/{db_id}/runs/{run_id}/diagram` (diagram-ready per-stage nodes with bootstrap CIs).
- `retrieval_observatory/mcp/server.py` — MCP server exposing 10 agent tools: self-describing
`describe_config` / `validate_config` (config schema + dry-run validation, no run), plus
`list_runs`, `get_run_metrics`, `benchmark_config`, `benchmark_vs_baseline`, `get_pareto_frontier`,
`get_recommendations`, `get_operator_attribution`, `get_pipeline_diagram`. New `retobs mcp` CLI
command and `[mcp]` optional-dependency group.
- `config/discovery.py` + REST `GET /config/schema` and `POST /config/validate` — let an agent
discover the ExperimentConfig shape and validate a config without running a benchmark.
- `retobs diagram <run_id> -o out.html` — export a read-only pipeline diagram (per-stage
Recall/NDCG/latency with 95% CIs) as a standalone, offline HTML file (`diagram/html.py`).
- Optional bearer-token auth via `RETOBS_API_TOKEN` and a concurrent-run cap via
`RETOBS_MAX_CONCURRENT_RUNS` (default 2) gating the run-trigger endpoints.
- `docs/integrations/api.md` and `docs/integrations/mcp.md` — agent/REST/MCP integration guides.
- `retrieval_observatory/cli.py` and `retrieval_observatory/mcp/` — added a simple `retobs mcp init` bootstrap flow plus YAML-driven defaults so agents can wire retobs into an existing pipeline with minimal setup.

---

## [0.4.1] — 2026-07-02

### Fixed

- `.github/workflows/retrieval-ci.yml` — golden gate re-runs healthy baseline config as candidate; demo’s degraded run is no longer compared (advisor check correctly exits 1 on intentional regression).

- Operator Attribution Grid always showed `not_applicable`: qrels used for scoring were never
persisted anywhere the dashboard could read them back from. Added a `run_qrels` store table
(SQLite + Postgres) written once per run by `execute_benchmark`, and wired both
`/operator-attribution` and `/miss-attribution` to read real ground truth from it.
- `tracing/lift.py` misclassified any dense-retrieval stage named `sentence-transformers/...`
(the standard model-naming convention) as a `TRANSFORM` operator instead of `SOURCE`, because
the naming heuristic substring-matched "transform" inside "transformers".
- `StagePipelineFlow.tsx`'s hybrid/RRF fan-in arm rendering could never receive arm-level metrics
because the frontend never requested `include_branches=true`; added a dedicated branch-inclusive
fetch for the pipeline architecture diagram.



### Added

- `docs/USAGE.md` — comprehensive usage guide: core concepts, YAML vs SDK, wiring retobs into an
existing pipeline, hybrid/multi-stage/DAG pipelines, production tracing, the dashboard, metrics
and attribution reference, CLI reference, CI gating.
- `examples/complex_rag_demo/` — a hybrid, multi-stage RAG benchmark (BM25 + dense fan-in via RRF,
cross-encoder rerank, custom recency-boost stage) comparing six architectures in one run.



### Changed

- `docs/` reorganized: maintainer/ops reference lives under `docs/informative/` (`ci_gating.md`, `PYPI_PUBLISH.md`);
restored `YAML_GUIDE.md`, which had been accidentally left untracked despite being linked from
README.md.

---



## [0.4.0] — 2026-07-01

This release completes the **trace-native revamp**: retrieval pipelines are now modeled as an operator DAG (`RetrievalTraceV2`) instead of a flat
list of stages, with honest, replay-tiered attribution of which operator helped or hurt each query.

### Added

- **Trace-native core model** — `RetrievalTraceV2`/`OperatorSpan`/`Candidate` operator-DAG schema, with a
lift path that upgrades legacy `PipelineResult` runs into valid DAGs (fused stages become first-class
`FUSE` spans with per-arm provenance) without changing any existing metric numbers.
- **Honest attribution engine** — per-segment, per-operator marginal contribution (recall/NDCG/precision/
MRR/MAP) with bootstrap confidence intervals, Benjamini-Hochberg-corrected significance, low-power
flags, and a `replay_policy` (exact / observed-ablation / not-replayable) so no result overclaims
certainty. Counterfactual replay (`without_operator`) correctly handles boosts, filters, reranks,
expansions, gates, and multi-arm fusion (RRF recompute on arm removal).
- **Miss attribution** — explains why a relevant document didn't surface (dropped by a specific operator,
never retrieved, or graph-reachable but not connected), including graph-aware evidence via a new
document edge store (thread/entity/reference relationships).
- **Production instrumentation on V2** — `ro.init()`, `@observe`, OTEL export, and a remote results client
all emit the same trace shape a benchmark run produces; LangChain and LlamaIndex integrations now emit
native operator spans instead of flat stage snapshots.
- **Dashboard: operator-native views** — segment × operator attribution grid, per-operator inspector,
operator DAG visualization, and a trace latency waterfall, backed by new DAG/diff/miss-attribution
endpoints.
- **Deployability** — `Dockerfile` + `docker-compose.yml` for a self-hosted single-tenant deployment;
Postgres DSN support in the dashboard registry; graph corpus ingest API; pgvector and Qdrant adapters
gain real metadata filter support.
- **Reference acceptance test** — a production-shaped pipeline (gates, multi-source fusion, expansion,
rerank, boost) exercised end to end as the north-star correctness check.



### Changed

- V2 dual-write is now **on by default** (previously opt-in), including for cache hits, timeouts, and
errors, so every run — not just the happy path — produces a trace.
- Metrics, diagnostics, and dashboard run/query views now compute from trace-native data first, falling
back to legacy snapshot-based computation only when V2 traces are absent.
- Replaced the `rank_bm25` runtime dependency with an in-process BM25 scorer; removed remaining Numpy-only
statistics helpers in favor of pure-Python implementations to avoid platform-level import crashes.
- Dashboard UX pass: pagination instead of hard row caps, glossary links fixed, indeterminate/low-power
states shown explicitly instead of misleading zero-gain verdicts.



### Fixed

- Seven correctness bugs in the attribution/replay engine from the initial trace-native cut: multi-gate
segment keys were truncated to the first gate, counterfactual replay didn't propagate through branching
DAGs, final-output detection assumed the last span in a list rather than following the DAG, async
graph-reachability checks were silently dropped, and FUSE arm removal didn't recompute RRF.
- Hybrid fan-in pipelines no longer mislabel successful queries as `candidate_miss`.
- Lazy schema creation so production tracing doesn't 500 on a fresh database.
- `retobs quickstart` no longer crashes on Rich markup or nested event loops.

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

- Reverted PyPI distribution name from `retobs` back to `retrieval-observatory`. Install with `pip install retrieval-observatory`.
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

- FastAPI live-tracing demo hardened with score-filtering for empty candidates, configurable latency budget, and expanded corpus for end-to-end trace verification.



#### Error messages and failure modes (task 1.5)

- Friendlier CLI/pipeline error messages: fail-fast missing extras at build time, YAML parse hints instead of raw tracebacks.



#### Docs (honesty pass)

- Docs honesty pass: LangChain/LlamaIndex callbacks labeled as real adapters; suspected-failure and difficulty signals labeled heuristic.



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
- README — new "benchmark your pipeline in Python (no YAML)" section; zero-label and pytest-gate snippets added.



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
- `results/BENCHMARK_ANALYSIS.md` — deep-dive Pareto analysis and statistical methodology
- `docs/YAML_GUIDE.md` — six copy-paste YAML templates + LLM prompt for generating configs
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
