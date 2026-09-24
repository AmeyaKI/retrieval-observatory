# Changelog

All notable changes to retrieval-observatory are documented here. Versions marked **[PyPI]** are published. Unreleased changes on `main` are at the top.

---

## [Unreleased]

### Added

- `integrations/model.py` — integration plan schema v2: per-operator `input_mapping` / `output_mapping` / `capture` (`retobs_adapter:<symbol>`) / `invocation`, scenario `command` and `route`, `boundary` (`FinalBoundary`), `identity` (`IdentityChoice`), `judgments`, `expected_capabilities` over the eight `CAPABILITY_NAMES`, `actions` (`install | source_edit | benchmark_setup | scenario_execution`, only source edits performed by apply), and non-blocking `open_questions`; `IntegrationPhase.REVERT`.
- `integrations/planner.py` — plans state per-operator input/output mappings (a static mirror of the runtime capture rules), the final boundary, candidate/query identity, discovered judgment files, expected capabilities, actions, a `representative-repeat` scenario with `python -c` commands, and an open question for every gap; `build_integration_plan(..., reviewed=)` re-plans from a reviewed plan's operators/scenarios (unknown symbols become `unresolved`; `capture` references land as `capture=retobs_adapter.<symbol>` in the decorator); instrumented modules carry a `# retobs instrumentation` marker line; `discovery.runbook` names the packaged runbook; the benchmark action names the run after the pipeline (`--name`).
- `integrations/apply.py` — `revert_integration`: restores apply's edits from the manifest and refuses when a patched file changed since apply; apply refuses, before writing, a `capture` reference that root `retobs_adapter.py` does not define. `retobs integrate --phase revert`, MCP `integrate_project(phase="revert")`; `--plan` / `plan_path` accepted by the plan phase for re-planning.
- `integrations/verify.py` — `verify_observed_traces` reports every §3.5 capability (`topology_observed`, `actual_input_output_capture`, `candidate_identity`, `query_identity`, `final_output_capture`, `judgment_mapping`, `declared_route_coverage`, `cross_run_entity_alignment`) as `ready | partial | unavailable` with evidence counts, a scope sentence and coded failures with fixes; graph invariants (`invocation_id_reused`, `parent_invocation_unknown`, `parent_inputs_unrelated`, `unobserved_transition_before_return`, `undeclared_operator_observed`) are checked per trace independently of the manifest; `missing_actual_inputs` names the `retobs_adapter` CaptureSpec to write; `judgment_mapping` loads `plan.judgments.qrels`; scenario coverage accumulates across declared scenarios (`unobserved`, `missing_by_scenario`, `observed_routes`); overall status is `failed` only when a core capability is unavailable and `partial` for limitations.
- `integrations/record.py`, `dashboard/integration_api.py` — `integrate --phase verify` persists an `integration` analysis record (plan summary, capability report, actions, open questions, `depth: internal | final_only`) in the trace database; `GET /dbs/{db}/integrations` and `GET /dbs/{db}/integrations/{service:pipeline}` (read-only) serve it with the first run carrying the pipeline as `investigation`.
- `dashboard/ui` — Connect lists the selected database's verified integrations and renders the selected record read-only: exact setup commands, plan summary with operator table, the eight verified capabilities with expected-vs-verified notes and failure fixes, unresolved mappings and open questions, and the first-investigation link.
- `sdk/observe.py` — `record_return_boundary`; `trace_scope` records the entrypoint's returned candidates as a `return` boundary span when they differ from the last observed operator's output and an unreadable result as `final_output_shape_unsupported`, never consuming iterators or raising; a `@observe("GATE")` function returning a route string (or a mapping of scalars) records it as `gate_values` instead of an unsupported output shape, and a gate parent is a topology edge, not a candidate input group.
- `tracing/capture.py` — `extract_outputs` reads a mapping's `documents | docs | candidates | hits | results` list.
- `examples/agent_integration/SKILL.md` (+ `references/plan-review.md`, `references/retobs_adapter_example.py`) — packaged agent runbook: discovery, reviewed plan, minimal patches, scenario runs, capability verification, labeled evaluation, investigation; required by the wheel content checks.
- `tests/external_projects/hybrid_multi_module/` — class-based multi-module hybrid fixture (gate, async fan-in, `*lanes` fusion captured through `retobs_adapter.py`) with a reviewed `plan_overrides`; `tests/external_projects/plan_review.py::apply_plan_overrides`; `tests/integration/test_agent_integration_workflow.py` runs plan → review → re-plan → apply → scenarios → verify (eight capabilities) → evaluate → Connect record → revert, plus final-only classification and packaged-runbook discovery.
- `integrations/registry.py::describe_integration` — `runbook_path` of the packaged runbook.
- `release/audit.py` — `build_release_audit` produces one versioned `audit-1` release audit (decision with exit code, sources and digests, policy identity and resolved selectors, compatibility with provenance classifications, readiness, coverage, per-check effects/intervals/tolerances, slices, operational accounting, statistics, changed queries linked into Investigate, paired metrics) shared by `retobs compare`, `BenchmarkReport.compare()`, MCP `compare` (`format="audit"`) and `POST /compare` (`audit` key); `render_audit_html` writes a standalone offline HTML report; `ReportModel.audit`.
- `retobs compare --artifacts DIR` writes `release-audit.json` and `release-audit.html` before the exit status is decided; `retrieval_observatory/examples/release-policy-golden-v3.yaml` (resolves on the rebuilt demo runs).
- `dashboard/ui` — Audit renders the `audit-1` artifact: decision with exit code and policy identity, compatibility with provenance classifications and claim readiness, checks, slices, operational accounting, changed-query links into Investigate, statistics and paired-metric details, JSON download, sources; the policy path is bound to the URL; servers without `audit` fall back to the release decision card.
- Baseline/candidate journey comparison: `tracing/lineage_diff.py::diff_journeys` joins two runs' journey rows on (query, namespace, unit, entity), classifies `lost | gained | membership_changed | rank_changed | path_changed | unchanged | unaligned` with final-outcome changes first, aligns queries by stable input identity and stages by `operator_id`, keeps each side's capture limitations, and blocks matched claims when the corpus changed; `GET /dbs/{db}/investigation/runs/{run}/compare?against=BASE[&query=]` and `.../compare/{query_id}`; Investigate accepts `compare=` and shows the comparison with a "Back to audit" link; Audit's changed-query list opens the exact query comparison in Investigate.
- `tracing/lineage_diff.py` — `diff_journeys`, `align_stages`, `summarize_journey_diff`: two runs' journey rows joined on (query, namespace, unit, entity), never on text; change `lost|gained|membership_changed|rank_changed|path_changed|unchanged|unaligned` and alignment `aligned|query_unaligned|entity_revision_changed|missing_in_baseline|missing_in_candidate|corpus_changed`; final-outcome changes sort first; stages pair by `operator_id`.
- `evidence/service.py`, `dashboard/investigation_api.py` — `compare_investigations` behind `GET /dbs/{db}/investigation/runs/{run}/compare[/{query}]?against=BASELINE[&against_pipeline=]`: both runs resolve under the candidate's evaluation spec, `assess_evidence` fills `comparison.compatibility` (provenance, findings, `corpus_changed`, `query_inputs_identical`), per-query alignment from stored query inputs, `comparison.stage_alignment` for one query, offset-cursor pages; findings `unsupported_corpus_change`, `comparison_partial`, `projection_unavailable` naming the run; GET never writes.
- `dashboard/ui` — Investigate `compare=BASELINE` mode: `CandidateLineageDiff` renders the journey comparison (Entity | Baseline | Candidate | Change with glyph and text, per-side capture limits, stage alignment, corpus-changed notice) with a "Back to audit" link; Audit's query-level diffs link "Open in Investigate" (`investigateLink({compare})`, `auditLink`); `comparisonDiffs.ts` change/alignment labels, sorting and totals.
- `release/statistics.py`, `release/slices.py`, `release/decision.py` — v3 policies are evaluated directly: `evaluate_resolved_checks` (per-run metric keys, pairs over the expected query universe with attempted/paired counts and pair coverage, estimator-aware paired bootstrap, family-wide adjusted confidence including slice `metric_ids`, bootstrap-resolution floor, inclusive non-inferiority boundaries), `evaluate_resolved_slices` (frozen benchmark membership, absent/small slices reported, never omitted), `evaluate_execution` (deterministic failure-rate cap over attempted queries; unknown attempt accounting blocks), and `decide_release_v3` (BLOCK > FAIL > HOLD > PASS with every result retained; `ReleaseDecision.operational`).
- Investigate: synchronized pipeline diagram (stable run-union layout, per-query execution overlay with status/capture glyphs, aggregate counts with denominators, collapsed repeated invocations with an expand control, zoom, accessible operator table), one primary table for queries / a query's candidates / documents / a document's queries (semantic headers, keyboard selection, outcome glyph + text, active filter chips, reset), and a journey detail panel (ordered transitions with recorded/inferred evidence, boundary capture with source reference and recorded configuration, content preview when captured, permalink). Selection and filters live in the URL.
- `release/policy.py`, `release/resolution.py` — release policy schema v3: semantic selectors (`target: final_retrieval | query | operator:<id>`), stable metric/slice ids, per-slice `metric_ids`, `evaluation` block (unit, boundary, k, threshold), `evidence` requirements, `statistics.min_pair_coverage` default 1.0, `execution.max_failure_rate`, strict validation including the bootstrap-resolution floor (`resamples * (1 - adjusted_confidence) / 2 >= 20`); `resolve_policy` binds every check to canonical per-run metric keys and reports `metric_selector_unresolved` (BLOCK) for absent or ambiguous selectors; `convert_v2_policy` maps v2 positional selectors to v3 or reports `policy_selector_ambiguous`; `load_release_policy` dispatches on `schema_version` 2 or 3. `examples/ci/release-policy-v3.yaml` documents the format.
- `sdk/report.py` — `release_decision.policy_resolution` (resolved checks and findings) and, for v2 policies, `policy_conversion`.
- Dashboard shell: exactly three workflows — Investigate (`#/investigate?db=&run=&pipeline=&view=queries|documents&query=&trace=&entity=&stage=&outcome=`), Connect (`#/connect?db=&integration=`), Audit (`#/audit?db=&baseline=&candidate=&policy=`) — plus Help (`#/help`) and theme as utilities; the URL is the single source of truth for scope, changing the run clears run-scoped selections, and `#/` lands on Investigate when any database has runs, else Connect.
- Legacy dashboard links redirect losslessly for one release (`#/runs/RUN[/queries[/Q[/candidates/DOC]]|/documents]`, `#/benchmarks/run/*`, `#/compare`, `#/glossary`); retired destinations (`#/home`, `#/queries`, `#/production`, `#/test-sets`, run attribution/tradeoffs/quality/architecture/analysis pages) show a migration notice instead of fabricated content.
- `sdk/api.py`, `sdk/wrappers.py` — `evaluate(callable, ..., provenance=..., chunk_map=...)`: an instrumented callable runs once per query inside an active trace, its `@observe` spans become the Run's trace (no synthetic single stage), the returned result is recorded as a `return` boundary when it differs from the last traced operator, and failed queries persist an ERROR trace with traceback. `provenance` fills `release_identity`; unknown keys are rejected, absent keys stay absent.
- `runner/execute.py` — manifests carry `judgment_records`, `judgment_digest`, `evaluation` (unit and the caller's k, else the largest configured recall cutoff), and `chunk_map`; one trace per (pipeline, query) is enforced; after `finish_run` the investigation projection is built per pipeline and its status (or a `repair` command) is recorded under `investigation_projection`.
- `retobs evaluate --provenance KEY=VALUE --chunk-map PATH`.
- `evidence/service.py`, `dashboard/investigation_api.py` — one scoped investigation service behind every transport: `GET /dbs/{db}/investigation/runs/{run}/queries[/{query}]`, `.../documents[/{entity}]`, `GET|POST .../projection`; envelope with `scope`, `capabilities`, `coverage`, `rows`, `total`, `next_cursor`, `summary`, `stages`, `findings`; 400/404/409/422 error codes; GET never writes, POST builds the projection explicitly.
- `retobs inspect-document RUN ENTITY`, `retobs storage migrate --db`, `retobs storage index RUN --db`; SDK `inspect_document(...)`; MCP tool `inspect_document`; `contracts/public_surface.json` updated in the same change.
- `dashboard/ui/src/api.ts` — TypeScript mirrors of the investigation envelope and fetch helpers.
- `evidence/service.py` — `inspect_investigation` list envelopes carry `stages`: the stored per-operator aggregates (`queries_served`, `queries_skipped`, `candidates_received`, `removal_events`, `introduced`, `partial_boundaries`, `operator_id`) once the projection is complete, else `null`.
- `dashboard/ui` — Investigate workspace: `InvestigationGraph` (run-union topology with the stored aggregate or the selected trace's status/capture overlay, path highlight for the selected journey, collapsed repeated invocations, zoom, legend, accessible operator table), `InvestigationTable` (queries, a query's candidates, documents, a document's queries; sortable headers, keyboard-selectable rows, live row count, removable stage/outcome chips, one reset), `InvestigationDetail` (ordered transitions with evidence labels, boundary capture, content preview or `IDs only`, permalink, evidence details); `utils/queryDebugger.ts` (`pathHighlight`, `outcomeLabel`, `outcomeGlyph`, `evidenceLabel`, `stageFilter`, `sortForView`, `queryRollups`, `transitionText`), `utils/dagLayout.ts` `collapseInvocations`.
- `evidence/investigation.py`, `evidence/journeys.py` — canonical journey projection: `project_trace_journeys(trace, judgments, spec)` emits one row per (query, evaluation entity) with per-occurrence events (`introduced|retained|promoted|demoted|removed|recovered|transformed|unknown`), recorded-vs-inferred reasons, boundary completeness, final membership at the evaluated boundary, confusion over the judged universe, capture state, loss boundary, and outcome; `summarize_journeys` counts unique pairs separately from events; `summarize_stages` reports served/skipped/received/removed per operator.
- `store/sqlite.py`, `store/postgres.py`, `store/base.py` — schema v3: `investigation_pairs`, `investigation_summaries`, `investigation_projections` with scoped indexes, keyset pagination (`list_investigation_pairs`, default 50, max 200), transactional `replace_investigation_projection`; read-only v2 databases stay readable with investigation reads returning empty results.
- `store/migrate.py` — `migrate_database(db_path, backup=True)`: additive v2→v3 upgrade with an online-backup copy taken first, idempotent, rollback on failure; `ensure_supported_schema` accepts versions 0, 2, 3.
- `tracing/model.py` — `OperatorSpan.operator_id` (stable operator identity; `op_id` is the per-trace node key, repeated invocations become `op#2`, `op#3` via `next_node_id`), `parent_invocation_ids`, `parent_linkage` (`recorded|declared|inferred|unavailable`); `RetrievalTrace.topology_hash()` hashes by operator identity so invocation count no longer changes the topology; `RetrievalTrace.invocations_of()`.
- `pipeline/dag.py` — every executor span carries `invocation_id`, `operator_id`, recorded input/output capture, and the producing spans' invocation ids (`parent_linkage = recorded`); skipped operators record no inputs.
- `tracing/capture.py`, `sdk/observe.py` — `@observe(..., capture=CaptureSpec(inputs, outputs, decisions))` records each operator's actual bound arguments (snapshotted before the call) and returned object; parent-span outputs are used only as a labelled `inferred` fallback. The wrapped function is called exactly once, its result object is returned unchanged, `BaseException` (including cancellation) propagates untouched, and capture failures land on `RetrievalTrace.capture_failures` instead of failing the call; `strict_capture()` raises `CaptureError` after the call for verification runs. Generators are never consumed and unsupported result shapes are recorded as `unavailable`, not as empty output.
- `tracing/model.py` — `OperatorSpan.invocation_id`, `input_capture` (`recorded|positional|inferred|unavailable|not_applicable`), `output_capture` (`recorded|truncated|unavailable`), `source_ref`; `CaptureMetadata.incomplete_boundary_count`; legacy payloads parse with `inferred`/`not_applicable` labels.
- `datasets/judgments.py` — `EntityRef`, `Judgment`, `JudgmentSet`, `EvaluationSpec`, `ChunkMap`, `resolve_relevance`, `confusion_counts`, `query_input_identity`: judgments scoped to (query, namespaced entity), stored grades with threshold-derived relevance, absent judgments stay `unjudged`, contradictory duplicates raise unless a conflict rule is given, document grades are not inherited by chunks, deterministic order-independent digests.
- `datasets/validation.py` — `dataset_fingerprint` gains `query_input_hash` (text, filters, metadata, anchor), `judgment_digest`, and `judgment_schema_version`; existing hashes unchanged.
- `tests/fixtures/investigation_cases.py` — executable deterministic golden hybrid pipeline (dense + lexical branches, recorded filter, repeated reranker invocation, RRF dedup, gated expansion, context selection) with a hand-authored expected journey table.
- `scripts/render_study.py` — renders `results/study/STUDY.md` from the per-cell JSON only: the headline sentence through the PREREGISTRATION.md §2 decision rule, pooled statistics recomputed from per-pair events with a (dataset, query) cluster bootstrap, per-dataset rows beside every pooled figure, the replay strategy and its recorded caveat next to every marginal contribution, and a labelled draft banner naming every missing cell; `--check` fails when the file is stale.
- `scripts/study_loss_attribution.py` — an interrupted cell's unfinished Run is deleted before the cell runs again (`purge_unfinished_runs`); each cell records final-stage per-query nDCG@10 and recall@10 (`per_query`) so paired ratios can be recomputed from committed files, and cells written before that field existed are backfilled from their own Run with no other key changed.
- `docs/guides/manual-instrumentation.md`, `examples/integrations/manual_class_pipeline/` — hand-instrumenting a class-based, multi-module pipeline with `@observe` and `@trace_scope`: cross-module `parent_ids`, declared op types and replay tiers, one persisted trace per entrypoint call; asserted by `tests/integration/test_manual_class_pipeline.py`.
- `scripts/study_loss_attribution.py` — idempotent grid driver for the pre-registered study: pipelines 1–4 and the fiqa reconciliation cell declared as `graphs:`, the flagship HotpotQA pipeline unchanged, runtime estimate per cell, every run through `execute_benchmark` into `results/study/results.db`, per-cell JSON with loss attribution, marginal contributions by replay tier, and per-pair events; completed cells are skipped; no latency rows in any artifact.
- `pipeline/factory.py` — `adapter.hf_biencoder` nodes accept `config.cache_dir` for the FAISS index cache.
- `analysis/loss_attribution.py` — per-(query, gold) attribution of recall misses to the last displacing operator from recorded ranks (`gold_events`, `attribute_run`, `summarize`, `self_inflicted_difference`): surfaced / never-surfaced / surfaced-never-in-window / destroyed outcomes, first and last displacer, recovery and re-displacement, loss share by operator class, query-cluster bootstrap intervals (2,000 resamples, seed 17).
- `tracing/attribution.py` — `operator_marginal_contributions()` (plural) applies one Benjamini-Hochberg family across every (operator, segment) p-value; the singular function's family is documented as segments-of-one-operator.
- `tracing/serialization.py`, `tracing/model.py` — `truncated_string_count` / `NormalizationReport.truncated_strings` count clipped strings separately; `omitted_field_count` is structural only, so a long metadata string no longer marks a trace's lineage partial.
- `metrics/engine.py` — per-query `<pipeline>|stage-1|failure@0` and `timeout@0` indicator rows, so failure rate is pairable and guardable.
- `release/policy.py` — `statistics.min_pair_coverage` (default 0.95): a guard returns HOLD with the failed-query counts when fewer than that share of attempted queries are paired.
- `store/sqlite.py`, `store/postgres.py` — `get_run_status_counts_by_pipeline()`.
- `results/analytics_extract.json` — `ci_method` and `pvalue_method` fields.
- `pipeline/dag.py` — `DEFAULT_REPLAY_POLICY`: the runner now declares a replay tier on every span (FUSE, FILTER, BOOST, and SOURCE-feeding-a-FUSE are EXACT; RERANK, EXPAND, GATE, TRANSFORM are OBSERVED_ABLATION; GENERATE and a lone SOURCE are NOT_REPLAYABLE); a spec param `replay_policy` overrides. Previously every runner-produced span was NOT_REPLAYABLE, so counterfactual replay never applied to real runs.
- `pipeline/deadline.py` — the runner publishes its per-query deadline; pipelines convert a cancellation into a TIMEOUT result only when that deadline fired, and re-raise otherwise.
- `adapters/*` — every adapter class declares `op_type`; `StageSnapshot.op_type` is set by list pipelines.
- `dashboard/api.py` — `/production/traces` implements the `difficulty` and `suspected_only` filters it previously ignored; `/operator-attribution` rows carry `pipeline_id`; `query_diffs` carries an explicit `orientation`; `/demo/context` carries `db_id`; `candidate-lineage-diff` accepts `against_db`.
- `store/sqlite.py`, `store/postgres.py` — unique index on the metric-row natural key; `save_metrics_batch` ignores duplicates.
- `experimental/advisor/recommend.py` — `compute_reliability(persist=...)`.
- `sdk/observe.py` — `@trace_scope(service_id, pipeline_id, db_path)`: starts, finishes, and persists a trace around an entrypoint; a no-op when a trace is already active. `integrate --phase apply` now wraps the plan's entrypoint with it, so `verify` finds a trace after one call of the instrumented code.
- `tracing/recorder.py` — a `TraceContext` publishes itself as the `@observe` current trace, so decorated functions called under `instrument_fastapi` or the LangChain/LlamaIndex callbacks land in that trace.
- `retobs integrate --framework` and MCP `integrate_project(framework=...)` override detection.
- `integrations/planner.py` — `discovery.low_confidence_operators` lists name-only matches (confidence 0.6) that are excluded from patches.
- `tests/fixtures/integration_projects.py` — three representative target projects (plain Python, FastAPI with a class-method retriever and reranker, LangChain `BaseRetriever`) exercised end to end by `tests/integration/test_integration_projects.py`.

### Changed

- `integrations/verify.py` — a declared operator absent from a trace is no longer `topology_identity` drift (`missing_by_trace` removed); `checks` is one entry per capability; `verify_project` passes the project root for judgment resolution; a scenario's expected path is checked per scenario, never "every operator in every trace".
- `sdk/wrappers.py` — `_record_return_boundary` delegates to `sdk.observe.record_return_boundary`.
- `scripts/smoke_external_project.py` — fixtures discovered from `tests/external_projects/conftest.py`; reviewed re-plan step; asserts `status == "ready"` and every capability `ready`; writes `capabilities.json`; repeats one query for cross-run alignment. `tests/external_projects/*/expected.json` list the eight verify capabilities (and `plan_overrides` where the review is needed); `tests/release/test_external_wheel.py` counts the discovered fixtures.
- `integrations/planner.py` — `retobs_adapter.py` is never scanned for operators; `positional_lanes` input mappings are expected `partial` with an open question (verify reports them as `inferred_inputs`); a gate's route-coverage expectation is `ready` once a scenario declares a `route`.
- `docs/integrations/AGENT_QUICKSTART.md`, `docs/integrations/mcp.md`, `docs/INTEGRATIONS.md` — reviewed re-plan, revert, the capability report and persisted record, the final-output-only limitation, and the measured fixture boundary (no unfamiliar-repository agent trial recorded yet).
- `MANIFEST.in` — the dashboard source tree (`dashboard/ui/src`) is no longer packaged; the built `dist` is.
- `retobs compare` exit status: FAIL 1, BLOCK 2, HOLD 3 (was 1 for all three under `--fail-on`); invalid `--fail-on`/`--format` 64 (was 2, which collided with BLOCK); comparison failure 70 (was 1). Documented in `docs/guides/retrieval-release-decisions.md`.
- `dashboard/api.py` — `POST /compare` derives its release decision from `build_release_audit` (v3 policies are judged by v3 checks; v2 evaluators are no longer called there) and labels a missing run as a comparison failure, not an invalid policy.
- `.github/workflows/retrieval-ci.yml`, `examples/ci/retrieval-ci.yml` — gate on the v3 policy with `--artifacts`, always upload the audit, and distinguish a non-PASS decision (exit 1–3) from a tool error.
- `retobs demo` — rebuilt on the packaged golden fixture (`retrieval_observatory/examples/golden_fixture.py`): two deterministic, model-free runs (a baseline whose recency filter loses `kb:doc-guide`, a validation run that repairs it) evaluated through the normal runner with document-level judgments, projections built, `demo_manifest.json` with `baseline_run_id`, `validation_run_id`, `sample_query_id`, `repaired_document`, `policy_path`; `--n-traces` is accepted and ignored; the CI example reads the policy path from the manifest.
- `runner/execute.py::execute_benchmark(judgments=)` — namespaced document-level judgments scored through `chunk_map`; `store/base.py::normalize_dataset_name`.
- `scripts/render_study.py`, `scripts/study_loss_attribution.py` are pinned research scripts (revision 29c67b8 / 0.6.0), off every test path; `scripts/bench_analytics.py` no longer emits `classifier`; `scripts/generate_dashboard_screenshots.py` keeps only the stage-contribution and recall-funnel figures.
- `dashboard/ui/src/components/OperatorInspector.tsx` — takes `{ opId, stage, aggregate }` from the investigation envelopes and reports served/skipped/received/removed/introduced/partial counts with denominators plus capture labels; no longer calls the retired operator-attribution or operator-DAG endpoints (`RunAttributionPage` drops it).
- `release/assessment.py` — release comparability separates evaluation invariants (query input identity, judgments, corpus revision and content, labeling, evaluation unit/k, metric versions → BLOCK on mismatch or missing), declared interventions (`policy.intervention.expected_changes`; an undeclared model/index/chunking change is a reviewable HOLD `undeclared_intervention`, never a BLOCK), and within-run index/encoder consistency (`index_encoder` block → `index_encoder_incompatible` BLOCK, `index_encoder_unverified` HOLD, or unknown). The blanket `release_identity_mismatch` equality check is removed; `release_decision.provenance_assessment` carries the field-level diff.
- `release/policy.py` — optional `intervention.expected_changes` and `evidence.require_index_encoder_compatibility` on the v2 policy.
- `evidence/query.py` — `inspect_query` evidence no longer imports the advisor; `findings` is empty with `availability.findings = "unavailable"` and the document embeds the canonical `investigation` envelope for the query.
- `tracing/candidate_journeys.py` — `build_candidate_journeys` is now an adapter over the journey projection; `miss_type` is always `None` (counterfactual miss attribution retired) and the module no longer imports `tracing/replay.py`.
- `sdk/observe.py`, `tracing/recorder.py` — a declared parent resolves to the latest invocation of that operator; actual inputs captured for a parent that never fired record a `producer_not_observed` capture failure instead of being dropped silently.
- `tracing/auto_instrument.py` — an auto-instrumented retriever is a SOURCE with no parents; the previous "parent is the last span" assumption is removed, and non-list results are recorded as `unavailable` output capture rather than an empty list.
- `tracing/integrations/langchain.py`, `llamaindex.py`, `_duck_typed.py` — spans carry the framework run/event id as `invocation_id`, `params.framework_parent_run_ids`, and `params.component_identity` (`stable|unstable`); their inputs are labelled `inferred`.
- `tracing/recorder.py` — `TraceContext.span` labels inputs reconstructed from parent outputs as `inferred` and accepts `input_groups=` for actual inputs.
- `datasets/custom.py` — `_load_qrels` rejects a repeated (query, doc) row whose grade differs from an earlier row, naming both lines; identical repeats and zero grades load unchanged.
- The published tree is now limited to the project's own documentation. Internal planning notes, hand-off records, and development session logs are kept locally and gitignored; `deploy/README.md` and `docs/deployment.md` carry the deployment facts a reader needs, and no published file points at an unpublished one.
- `scripts/study_loss_attribution.py` — `repo_relative()`: `db_path` and `index_cache_dir` are recorded relative to the repo root, so committed cell records are machine-independent and identical runs on different machines produce identical JSON. The nine existing cell records were rewritten in place; no metric, rank, or run identifier changed.
- `results/study/PREREGISTRATION.md` — §8 reworded to describe the prior published claim in the project's own terms; recorded as an editorial amendment, with no methodological change.
- `results/flagship_demo/CASE_STUDY.md` — Scenario B leads; Scenarios C and C2 are an appendix.
- `dashboard/ui/src/components/OperatorInspector.tsx`, `SegmentOperatorGrid.tsx`, `VerdictCard.tsx` — an `indeterminate` / `not_applicable` / error attribution result shows its `reason` as visible truncated text (full text on hover) next to the status, via `InlineReason.tsx`; previously the reason was a tooltip or absent.
- `pipeline/graph_contract.py`, `pipeline/graph_projection.py`, `dashboard/pipeline_graph.schema.json` — `GraphMetricValue` carries the aggregate's `n` (optional, additive), so a node's mean states how many queries it covers.
- `dashboard/ui/src/components/PipelineDagView.tsx` — a branch node, or any node whose metric `n` is below the pipeline's trace count, shows "N of M queries served" under each value in the node inspector (and in the card tooltip); a gate-skipped branch's mean is never read as a full-run mean.
- `tracing/replay.py` — strict counterfactuals: removing an operator recomputes RRF for FUSE children and otherwise keeps each descendant's observed outputs filtered to what still flows in; a child that would have to decide on documents it never observed makes the replay `indeterminate` instead of receiving fabricated outputs. Multi-parent passthrough targets merge groups by candidate id; SOURCE removal only touches descendants and keeps documents another surviving arm found; every fuse child of a removed source is recomputed; the leaf-target "next span" fallback is gone; projected ranks are renumbered; the RRF constant is read from `rrf_k`.
- `tracing/candidates.py` — a candidate that passed through an EXPAND/BOOST/etc. keeps its previous `add_reason`; only newly introduced rows get the operator-type reason.
- `tracing/candidate_history.py`, `tracing/replay.py` `attribute_miss` — non-FIRED spans are ignored, `introduced_at` is never overwritten, and drops on branches that do not reach a final span are noted rather than counted.
- `metrics/engine.py` — `SKIPPED_BY_GATE` spans emit no metric rows: a branch's mean is its quality on the queries it served, with its own `n`. Previously every skipped query contributed 0.0, so branch rows equalled quality × routing share (the flagship funnel's 0.4462/0.4288 rows).
- `metrics/engine.py` — `failure_rate`, `timeout_rate`, `dropout_count` are computed per pipeline; count rows carry no interval; `_std` is the sample standard deviation.
- `metrics/comparison.py`, `sdk/report.py` — metric direction and effect thresholds are decided on the parsed metric name, never on the full key; `failure`/`timeout`/`dropout` are lower-is-better.
- `metrics/ranking.py` — graded nDCG uses linear gain (pytrec_eval/BEIR parity) and clamps negative grades to 0.
- `metrics/significance.py` — `paired_bootstrap_test` returns `(k+1)/(n+1)` so p is never exactly 0 and is documented as a sign-flip permutation test.
- `scripts/bench_analytics.py` — p-values come from the package's sign-flip test; the previous in-script bootstrap was not a valid test (its p-values were ~0.5 by construction). `results/analytics_extract.json` regenerated: every `vs_bm25_ndcg_pvalue` is now 0.0001–0.0003; all other fields unchanged.
- `docs/guides/counterfactual-replay.md` — documents the strict rule, the `rrf_k` key, and cross-operator BH.
- `pipeline/executors.py` — a graph node's configured `k` is applied to the query (spec `k` wins over the query's `k`); RERANK and FUSE record `top_k` in span params, and the executor-side cut is recorded as `drop_reason="truncated"` instead of being inferred as `reranked_out`.
- `pipeline/dag.py` — duplicate candidate ids from an adapter are de-duplicated (first wins) and listed in span params as `dropped_duplicates` instead of escaping as a `ValueError` that the runner retried.
- `runner/benchmark.py` — a TIMEOUT result is not retried; `_linear_trace` records each stage's real operator type (SOURCE, FUSE, RERANK, TRANSFORM) and input/output ranks instead of labelling every non-first stage RERANK.
- `runner/cache.py`, `pipeline/multi.py` — result and stage caches are keyed on dataset name, corpus hash, and query text in addition to the pipeline config, so editing the corpus no longer returns stale results.
- `runner/manifest.py`, `pipeline/factory.py` — the manifest's model inventory reads `config.model` (previously always null); a stage-level `model:` is honoured as a fallback.
- `adapters/bm25_adapter.py` — no zero-score padding: fewer than `k` results are returned when fewer documents match.
- `adapters/hf_biencoder_adapter.py` — over-fetches before applying `doc_ids` filters so filtered searches still return `k` results.
- `datasets/custom.py` — query ids and inline `relevant_doc_ids` are stringified like corpus and qrels ids.
- `dashboard/api.py` — production service, trace-list, and trace-detail responses go through `_monitor_trace`, so the fields the UI reads (`service`, `total_latency_ms`, `suspected_failures`, `stages`) exist; the key sets are asserted by tests.
- `dashboard/api.py` — per-query comparison deltas are candidate minus baseline, matching the declared orientation; the UI colours a positive delta as candidate-better. Previously the candidate's regressions rendered as wins.
- `dashboard/api.py` — arm-versus-fused ablations pair each arm with the spine node it actually feeds (topology), not the node at the same depth; on the flagship run every arm now has deltas instead of none.
- `dashboard/api.py` — operator attribution is computed per pipeline with one Benjamini-Hochberg family per pipeline; a failing operator yields an error row instead of a 500.
- `dashboard/api.py` — `GET …/advisor/reliability` and `GET …/runs/{run}/metrics` no longer write (snapshot persistence and metric recomputation happen without saving); both returned 500 on the read-only hosted demo.
- `dashboard/api.py` — `aggregate()` and stage contributions are memoised per (database, run, row count); one-query views load only that query's traces; `/diagram` builds its graph once. Flagship-run warm `/overview` 4.4s → 0.08s, `/queries/{qid}` 2.5s → 0.01s, `/diagram` 12.3s → 2.3s warm.
- `store/migrate.py` — reset removes every table the store creates (previously left `diagnostic_findings` and `analysis_records`).
- `store/sqlite.py` — query lineage counts services by `service_id` and scopes the Test Set origin lookup to the run's dataset.
- `mcp/server.py` — the config-defaults wrappers preserve each tool's signature; every tool exposed named parameters again. Previously nine of eleven tools advertised `args`/`kwargs` and rejected every call from a real MCP client.
- `integrations/verify.py` — `ready` requires, per scenario, a FIRED span with at least one candidate carrying a `doc_id`, a non-empty query text, and positive wall-clock time, and runs the stricter integration checks; a missing trace names the service, pipeline, and database path it looked for.
- `integrations/planner.py`, `integrations/detect.py` — files under `tests/` and `test_*` functions are never instrumented or required; class methods are discovered; FastAPI route handlers are entrypoints, not operators; framework scoring no longer lets the per-file `python` baseline outvote framework signals.
- `sdk/wrappers.py` — LangChain retrievers are recognised by `BaseRetriever` (or `invoke` + `_get_relevant_documents`), not the `get_relevant_documents` method removed in langchain-core 1.0.
- `cli.py` — `retobs evaluate` exits 1 when no query completed and prints the first error traceback tail; the progress bar goes to stderr so `--format json` is parseable; file-path targets can import sibling modules.
- `sdk/report.py` — headline metrics show one row per metric name (largest k), ordered ndcg, recall, mrr, per pipeline's terminal stage; `evidence_health` is `failed` when nothing completed and `limited` when some queries failed.
- `datasets/custom.py`, `config/discovery.py` — both qrels row shapes (`doc_id`/`relevance` and `relevant_doc_ids`) load; `validate_config` reports a dataset-file schema mismatch instead of passing a file that later raises `KeyError`.
- `integrations/service.py` — verify errors when the supplied plan's id differs from the applied manifest; a relative `db_path` resolves against the project root; verify without a manifest and plan on a nonexistent root return failed results instead of tracebacks; re-applying says "already applied".
- `mcp/server.py`, `sdk/api.py` — `push_traces` names the missing field, empty `run_id` and `max_queries < 1` are rejected.
- `examples/integrations/fastapi_search/app.py`, `integrations/registry.py` — rebuilt on the real API (`ro.init`, `instrument_fastapi`, `TraceContext.span`); a test imports every example app.
- `docs/INTEGRATIONS.md`, `docs/integrations/AGENT_QUICKSTART.md`, `docs/integrations/mcp.md` — corrected: reversal patches live in `retobs/integration.yaml`, what `ready` requires, verify's plan handling, LangChain version support.
- `dashboard/api.py` — `GET …/runs/{run}/metrics` computes when per-stage rows are absent; run-level status rows no longer suppress the computation.

### Fixed

- `store/sqlite.py`, `store/postgres.py` — traces whose candidate metadata carries application objects (`datetime`, `Path`) persist as text (`store.base.json_default`) instead of failing `retobs evaluate` on an instrumented callable.
- `tracing/candidates.py` — candidate ids are read from LlamaIndex nodes (`node_id`, `id_`, `NodeWithScore.node`) instead of falling back to positional ids.
- `cli.py` — `retobs evaluate --qrels` accepts one-pair-per-row judgments (`{query_id, doc_id, relevance}`) and a one-row JSONL file.
- `evidence/service.py`, `dashboard/ui` — Investigate's queries list is the stored per-query summaries (`scope.rows_kind = "query_summaries"`, exact `total`, keyset cursor, `query_id=prefix*`) instead of a client-side rollup of one 50-row pair page, so the header count and a query's delivered/missed no longer understate queries whose pairs straddled pages; per-query summaries gain `query_text`, `relevant_delivered`, `relevant_missed`, `unjudged_included`, `unknown_capture`, `loss_boundaries`; a pair-level filter keeps pair rows (`rows_kind = "pairs"`, finding `filtered_pairs`) and the table says "N candidate rows across M queries (filtered)".
- A declared reranker or embedding model change no longer blocks a release comparison on identity alone (`tests/unit/test_release_intervention_contract.py`).
- `pipeline/factory.py` — a RERANK node in a config-built graph now scores real passage text. Candidates carry `metadata` but not a document's `text` attribute, and the bm25 and dense sources return text only as an attribute, so `adapter.hf_crossencoder` and `adapter.cohere_rerank` scored `(query, "")` for every candidate and reordered by noise. `CorpusTextReranker` fills empty text from the corpus by id and never replaces text an upstream operator supplied. On scifact the cross-encoder's marginal nDCG@10 went from −0.145 to +0.042. Linear `pipelines:` and the flagship demo (which already re-read text in its own reranker) were unaffected.
- `tracing/replay.py` — a removed final operator hands its terminal role only to FIRED parents; a gate-skipped sibling with no outputs could previously become the counterfactual final output, so the marginal contribution of a terminal fuse read as the entire metric.
- `tracing/model.py` — `RetrievalTrace.from_dict` reads a legacy singular `final_op_id`.
- `pipeline/factory.py` — a RERANK node in a config-built graph now scores real passage text. Candidates carry `metadata` but not a document's `text` attribute, and the bm25 and dense sources return text only as an attribute, so `adapter.hf_crossencoder` and `adapter.cohere_rerank` scored `(query, "")` for every candidate and reordered by noise. `CorpusTextReranker` fills empty text from the corpus by id and never replaces text an upstream operator supplied. On scifact the cross-encoder's marginal nDCG@10 went from −0.145 to +0.042. Linear `pipelines:` and the flagship demo (which already re-read text in its own reranker) were unaffected.
- `analysis/scores.py` — calibration bins are half-open; boundary scores were counted twice.

### Removed

- `retrieval_observatory/experimental/` (forge synthetic generation, learned difficulty classifier, advisor recommendations/regressions/reliability/simulate, HTML diagram renderer) and the import-time compatibility shim; SDK `TestSet` and `generate_testset` (no replacement: import an externally prepared benchmark); CLI `testsets` and `production` subcommands; the `classifier` extra (`scikit-learn`, `joblib`); `tracing/enrich.py`, `metrics/diagnostics.predict_retrieval_risks`, store `get_forge_datasets`, `execute_benchmark(annotate_difficulty=)`. Historical `forge_*`, `reliability_snapshots` and `query_diagnostics` tables stay readable. Pinned reproduction in `docs/guides/experimental/README.md` (0.6.0 / 29c67b8).
- `tracing/replay.py`, `tracing/attribution.py`, `metrics/pareto.py`, `tracing/monitor/` (drift, hotspots, clusters, distribution), `analysis/{cohorts,corpus_health,service,loss_attribution}.py`; seven unregistered MCP helpers.
- `dashboard/api.py`, `dashboard/analysis_api.py` — forge, advisor, classifier, pareto-frontier, operator/miss attribution, replay candidate passport, operator diff, production summary/distribution/drift/hotspots/clusters, cohorts and corpus-health routes (with their legacy twins) now return 410 `{code: "retired", replacement}`; `/dbs/{db}/runs` no longer adds `forge_dataset_id`.
- `dashboard/ui` — retired workspaces, run pages, production and test-set views and their `api.ts` clients (92 unreachable files); legacy URL scope keys `service/window/since/until/cohort/filter`; Help no longer lists difficulty, drift or reliability.
- `sdk/report.py` — `assert_no_regression` no longer imports `experimental.advisor.regression`; it reads the audit's paired metrics.
- Dashboard operator-attribution and recommendation diff sections of the run comparison (retired counterfactual attribution and advisor features); `utils/comparisonDiffs.ts` now holds journey-diff helpers only.
- `dashboard/ui` — `RunComparisonDeepDiffs` attribution and recommendation diff sections, `comparisonDiffs.ts` `diffAttribution`/`diffRecommendations`; the retired `#/runs/RUN/queries/Q/diff` link from Audit.
- Dashboard navigation entries Home, Runs, Queries, Production, Test Sets, Compare, the platform tour, and demo quick links; the scope bar's window and cohort selectors. Their component files remain in the tree until the retirement task deletes them; none are bundled.
- `cli.py` — the never-registered `classifier`, `forge`, `tracelens`, `advisor`, and `golden` Typer groups and the unregistered `diagram` command (about fourteen dead commands).

---

## [0.6.0] — 2026-09-14

Consolidated surface, hosted demo. `advisor`, `forge`, `diagram`, and `classifier` move to `retrieval_observatory.experimental`; the README leads with per-stage attribution; a read-only BEIR dashboard is live on Azure Container Apps.


### Added

- `retrieval_observatory/experimental/` — new home for demoted subsystems; `experimental/_compat.py` installs a meta-path shim so `retrieval_observatory.{advisor,classifier,diagram,forge}` still import (same module objects) with a `DeprecationWarning`.
- `docs/guides/experimental/` — guides for demoted or unverified subsystems.
- `docs/deployment.md`, `deploy/README.md` — Azure Container Apps path for a read-only BEIR dashboard with the public-exposure checklist and its results; no core-package cloud deps.
- `deploy/Dockerfile` — hosted-demo image: baked read-only databases (`chmod 444`), non-root user, `RETOBS_READ_ONLY=1`, `RETOBS_RATE_LIMIT_PER_MINUTE=300`.
- `deploy/prepare_data.py` — bakes demo databases: copy, migrate schema once writable, verify `mode=ro` open, mark read-only. Baked files committed under `deploy/data/`.
- `deploy/deploy_azure.sh` — idempotent one-command deploy (group, environment, app create/update, `/healthz` poll).
- `.github/workflows/demo-image.yml` — builds `deploy/Dockerfile` and pushes `ghcr.io/<owner>/retrieval-observatory:demo` on dispatch or on `main` pushes touching the app or `deploy/`; smokes `/healthz` and a 403 write.
- `dashboard/api.py` — `RETOBS_READ_ONLY` returns 403 on mutating writes; `POST /compare` and `POST /compare/config-diff` stay allowed.
- `dashboard/api.py` — `GET /healthz`; per-IP sliding-window rate limit (`RETOBS_RATE_LIMIT_PER_MINUTE`, keyed on first `X-Forwarded-For` hop, 429 + `Retry-After`), on by default only in read-only mode.
- `dashboard/registry.py` — `hosted_read_only()`; `DbRegistry(read_only=…)` opens SQLite stores read-only and reports database basenames instead of filesystem paths.
- `store/sqlite.py` — `SQLiteStore(read_only=True)` connects with `file:…?mode=ro`; `init_db` runs no DDL in that mode and raises naming missing tables.

### Changed

- `README.md` — leads with the one-sentence positioning (which stage earned or destroyed the metric, with auditable attribution), the Scenario D lineage trace, install, and `retobs demo`; adds an "Attribution you can audit" section naming candidate lineage and counterfactual replay; drops leading jargon and links `docs/guides/README.md` and `FUTURE_WORK.md`.
- `advisor/` → `experimental/advisor/` — demoted; dashboard Findings, MCP, and `compare` regression detection still import it from the new path.
- `forge/` → `experimental/forge/` — demoted; `retobs testsets` and SDK `generate_testset`/`TestSet` remain public and are backed by it.
- `diagram/` → `experimental/diagram/` — demoted; the unregistered `diagram` CLI helper imports it from the new path.
- `classifier/` → `experimental/classifier/` — demoted; `tracing/enrich.py` and `runner/execute.py` keep using its feature extractor and model loader.
- `docs/guides/{advisor,forge,auto-instrumentation,conditional-pipelines,multi-stage-reranking,parallel-retrieval}.md` → `docs/guides/experimental/`; `docs/guides/README.md` lists only the six production guides.
- `docs/ARCHITECTURE.md`, `FUTURE_WORK.md` — describe the experimental tier and the classifier's missing label source.

### Fixed

- `dashboard/api.py` — `GET /dbs/{db}/runs/{run}/traces` declared a dict response but returned a list, so every call failed response validation with a 500.
- `dashboard/api.py` — `since`/`until`/`baseline`/`recent` that are not ISO-8601 return 422 instead of 500; `limit`/`offset`/`k` on production traces, topology variants, reliability history, Test Set queries, operator attribution, miss attribution, and query winners are bounded (422 outside range).
- `dashboard/api.py` — `policy_path` (a server filesystem path) on `POST /compare`, `POST /dbs/{db}/compare`, and `GET …/candidate-lineage-diff` returns 403 in read-only mode.
- `.dockerignore` — excludes `results/`, `dist/`, `artifacts/`, `*.egg-info`, `*.jsonl`, `*.png` so local runs, build outputs, and session transcripts never enter an image.

### Removed

- `cli.py` — `retobs classifier` subcommand unregistered (`contracts/public_surface.json` updated); it had no label source since `difficulty_bucket` is always `"unknown"`.

---

## [0.5.6] — 2026-08-07

### Added

- `results/flagship_demo/` — HotpotQA flagship demo: eleven-operator gated DAG, release policy, five runs, and decision reports for four scenarios (improvement, regression, provenance contradiction, stale index) plus a per-query lineage read-out. One command, no API keys.
- `metrics/comparison.py` — `rank_metric_keys()` orders metric keys by release-decision relevance (policy-guarded, terminal-stage quality, funnel, operational).
- `FUTURE_WORK.md` — published record of known limitations and deferred work.

### Changed

- `README.md` — leads with `retobs demo`, a zero-argument, no-key command, before the placeholder `evaluate` example.
- `results/BENCHMARK_ANALYSIS.md`, `results/RESULTS_OVERVIEW.md` — record the version, commit, and date the BEIR sweep actually ran at (0.1.0, `0991e64`, 2026-06-01) and state it has not been rerun since. Removes the incorrect "v0.1.2" label.
- `results/flagship_demo/CASE_STUDY.md` — separates seeded, exactly reproducible quality metrics from unseeded machine-dependent latency figures, and labels the latency table accordingly.
- `.gitignore` — allowlists `FUTURE_WORK.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `.github/**/*.md`, which the blanket `*.md` rule had silently excluded from version control.
- `store/base.py` — `TraceQuery.limit` defaults to `None` (every matching trace) instead of `200`; paging callers pass a limit explicitly. Removes the `limit=1_000_000` / `limit=100000` workarounds in `cli.py`, `dashboard/analysis_api.py`, and `dashboard/api.py`.
- `store/sqlite.py`, `store/postgres.py` — `list_traces` omits `LIMIT` when `TraceQuery.limit` is `None`.
- `dashboard/api.py` — comparison rows ordered by `rank_metric_keys()` instead of alphabetically, so terminal-stage quality leads instead of run-level operational rows.
- `sdk/report.py` — `_headline_metrics` selects terminal-stage quality via `parse_metric_key` and an explicit quality allow-list; `to_markdown` preserves that order instead of re-sorting alphabetically.

### Fixed

- `integrations/planner.py` — `_import_insertion_line()` places the instrumentation import after the shebang, module docstring, and every `from __future__` import. Previously it was inserted at line 0, which demoted the module docstring to a bare expression and produced a `SyntaxError` on any file using `from __future__ import annotations`.
- `integrations/planner.py` — `_instrument_source()` inserts decorators before the import so `node.lineno` stays valid, removing the index-shifting correction, and `ast.parse` validates the result before it becomes a patch.
- `integrations/apply.py` — `apply_integration_plan()` rejects a patch whose replacement does not parse, naming the file and parse error, instead of writing it and reporting `applied`.
- `integrations/verify.py` — `verify_observed_traces()` reports "no traces recorded" as the cause when no traces exist, instead of listing every declared operator as missing.
- `metrics/comparison.py`, `sdk/report.py` — `collapse_latency_render_keys()` replaces the `latency_p50`/`p95`/`p99` rows in comparison reports with a single `latency_mean` row. A paired comparison resolves all three to the same per-query `latency_ms` samples, so the report printed one mean under three percentile labels. Single-run `retobs report` percentiles are unchanged and remain true percentiles.
- `tracing/candidates.py` — `FUSE` outputs matching several inputs are graded `identity_evidence="recorded"`, not `"partial"`; multi-match is the defined behaviour of a fan-in, and the downgrade raised a permanent `lineage_capture_partial` BLOCK on fully instrumented hybrid pipelines.
- `sdk/report.py` — report headline metrics no longer omit recall/ndcg on multi-stage pipelines; the previous `|stage-1|` filter could only match run-level operational rows.
- `store/*` — `get_traces(run_id)` returns every trace for a run instead of silently truncating at 200, which had reduced run-wide statistics (notably MCP `operator_marginal_contribution` intervals and dashboard metric recomputation) to a prefix of the run.
- `release/evidence.py` — `_trace_is_partial` ignores `SKIPPED_BY_GATE` spans when checking for absent parent input groups; a branch a gate declined to run is recorded on the gate, not missing, and counting it marked every conditionally-routed pipeline as partially captured.

---

---

## [0.5.5] — 2026-07-30 [PyPI]

Release-identity comparability enforcement, restored `mcp`/`classifier` CLI subcommands, and working LangChain/LlamaIndex tracing examples.

### Added

- `cli.py` — register `retobs mcp` and `retobs classifier`, which were defined but never attached to the root command and returned "No such command". `contracts/public_surface.json` now lists both in `cli_commands`.

### Changed

- `mcp/server.py` — resolve `mcp` 2.x `MCPServer` when 1.x `FastMCP` is unavailable.
- `integrations/registry.py` — `describe_integration("langchain"|"llamaindex")` snippets now reference the real `RetobsLangChainCallback`/`RetobsLlamaIndexCallback` classes (and construct the required `OperatorRegistry`) instead of nonexistent `...CallbackV2` classes.

### Fixed

- `release/assessment.py` — a release-identity field (`corpus_revision`, `index_build_id`, `chunking_revision`, `embedding_model_revision`, `reranker_model_revision`) that is present but differs between baseline and candidate now BLOCKs the release decision, matching the existing dataset-hash-mismatch behavior. Previously only presence was checked, not equality.
- `scripts/check_public_surface.py`, `tests/contracts/test_public_surface.py` — list MCP tools via public `list_tools()` so source-gates work under `mcp` 2.0 (no `_tool_manager` on fallback).
- `examples/integrations/langchain_search/app.py`, `examples/integrations/llamaindex_search/app.py` — fix `ImportError: StoreSink` (renamed to `BufferedTraceSink`) and use `ro.init()` plus an `OperatorRegistry` binding, matching the real callback constructors. Both examples now run end-to-end and produce real trace rows.

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
