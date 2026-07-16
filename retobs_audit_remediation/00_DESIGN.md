# Retrieval Observatory Audit Remediation Design

**Status:** Approved design direction

**Date:** 2026-07-15

**Source:** `RETOBS_EXTERNAL_AUDIT_2026-07-15.md`
**Release posture:** Clean beta reset; backward compatibility with deprecated or legacy surfaces is explicitly out of scope.

## 1. Objective

Turn Retrieval Observatory into a coherent, V2-only retrieval reliability platform that an engineer or coding agent can integrate into a custom hybrid, gated, multi-branch RAG pipeline through one factual public workflow. The resulting instrumentation must preserve the real execution graph, remain isolated from application availability and latency, expose evidence limitations, and support scalable offline and production investigation.

Success means all audit findings are resolved, not merely hidden or documented. Public examples, CLI behavior, MCP behavior, storage, verification, APIs, dashboard states, package artifacts, and tests must agree.

## 2. Non-negotiable product decisions

1. **One public integration workflow:** `retobs integrate <project>` and MCP `integrate_project` expose `plan`, `apply`, and `verify` phases with equivalent contracts.
2. **V2 only:** remove V1 trace models, V1 persistence, V1 production readers, legacy recorders, dual-path adapters, and compatibility aliases.
3. **No deprecated vocabulary:** remove `wire`, `bootstrap_project`, `TraceLens`, `Forge`, `Advisor`, and `Benchmarks` as public commands, tools, routes, or peer-product names. Internal modules may be renamed when touched; no public documentation may teach the old terms.
4. **Observed truth over inference:** integration verification proves stable identity, topology, candidate transitions, timing, and coverage from representative traces. File presence is not readiness.
5. **Application wins over telemetry:** instrumentation cannot fail a retrieval request, block indefinitely, or grow memory without bounds.
6. **One identity model:** evaluation and production share service, run, trace, query, pipeline, operator, candidate, corpus, dataset, and index-version semantics.
7. **Evidence is typed:** every metric, diagnosis, recommendation, alert, and chart states its evidence class, method/version, sample, thresholds, limitations, and unavailable reason.
8. **Clean break:** current beta databases may be reset or explicitly upgraded once. No indefinite dual-read or deprecated-command migration layer will be built.
9. **Local-first safety:** dashboard servers bind to `127.0.0.1` by default; remote exposure requires explicit configuration.
10. **No feature is complete without installed-package and live-product proof.**



## 3. Program structure

The work is split into eight dependency-ordered workstreams:

1. Public integration contract
2. Unified V2 trace and storage model
3. Non-blocking and safe telemetry
4. Faithful DAG semantics and framework adapters
5. Diagnostic and evidence correctness
6. Core dashboard scale and navigation
7. Retrieval-analysis products
8. Documentation, packaging, and release proof

Workstreams 1 and 2 establish the public and data contracts. Workstream 3 makes production capture safe. Workstreams 4 and 5 make the data causally useful. Workstreams 6 and 7 expose the contracts at scale. Workstream 8 continuously validates and finally releases the coherent product.

## 4. Target architecture



### 4.1 Integration control plane

`integrate_project(project_root, phase, options)` is the single application service used by CLI and MCP.

- `plan` performs read-only discovery and produces a typed `IntegrationPlan`.
- `apply` validates plan identity, applies only approved patches, writes a manifest, and returns an exact change record.
- `verify` executes or consumes representative traces and produces a capability matrix.

The plan contains:

- detected framework, entrypoints, routes, retrievers, operators, and datasets;
- stable operator IDs and declared parent IDs;
- candidate/document ID, score, rank, metadata, and text mappings;
- service, pipeline, corpus, dataset, and index identity;
- redaction, sampling, queue, and payload settings;
- exact patch operations with precondition hashes;
- unresolved mappings and confidence per mapping;
- verification queries and expected operators/topology variants.

`apply` refuses ambiguous or stale plans. A coding agent may resolve uncertainties by editing the plan before applying it, but the tool must never silently invent a retriever, dataset, route, or graph edge.

### 4.2 Instrumentation manifest

The applied project owns a small `retobs/integration.yaml` manifest. It is declarative evidence of intended instrumentation, not an alternate pipeline implementation.

The manifest defines:

- schema version;
- service and pipeline identity;
- operator registry and parent relationships;
- framework binding or code symbol for each operator;
- candidate normalization rules;
- dataset/corpus/index identity sources;
- privacy/redaction policy;
- sampling and telemetry queue policy;
- representative verification scenarios.

The application continues to execute its own pipeline. Retobs observes declared boundaries and never becomes the orchestration runtime unless the user explicitly builds a retobs-native evaluation pipeline.

### 4.3 Unified trace contract

One `RetrievalTrace` contract replaces V1/V2 terminology. It contains:

- stable service and pipeline IDs;
- optional evaluation run ID;
- required trace ID, query ID, and timestamp;
- optional dataset/corpus/index versions;
- operator spans with stable IDs, declared parents, status, timing, parameters, gate values, inputs, outputs, and errors;
- explicit final operator(s);
- wall-clock, critical-path, and operator-sum timing;
- sampling and capture metadata;
- schema and instrumentation versions.

Production traces do not require a run. Evaluation traces attach to a run while retaining the same operator/candidate representation.

The store exposes domain queries such as `list_services`, `list_traces`, `get_trace`, `get_run_traces`, `list_topology_variants`, and `get_instrumentation_health`. Dashboard code does not query V1/V2-specific storage paths.

### 4.4 Telemetry data plane

Recording a span updates only in-memory trace state. Finishing a request enqueues a normalized immutable trace into a bounded queue and returns.

The background exporter:

- batches writes;
- has bounded retry with jitter;
- drops according to an explicit overflow policy;
- records accepted, exported, dropped, serialization-failed, retry, queue-depth, and flush-latency counters;
- supports deterministic shutdown flushing with a deadline;
- redacts and size-limits fields before persistence;
- cannot raise into application code.

SQLite remains the local default. The sink interface allows PostgreSQL or HTTP export without changing recorder behavior.

### 4.5 Graph and operator semantics

Operator identity is deterministic and stable across traces. Parent relationships come from the integration manifest or a framework's actual run tree/DAG, never merely from “previous span.”

Every executable operator type has defined input/output behavior:

- `SOURCE`: no candidate parents; produces candidates.
- `FUSE`: consumes all declared parent candidate lists and emits a fused ranking.
- `RERANK`: consumes one logical candidate set assembled according to declared parent semantics.
- `FILTER`: consumes candidates and retains/removes them with recorded reasons when available.
- `GATE`: records the decision and explicitly marks unselected branches as skipped.
- `BOOST`: changes scores/ranks while preserving candidate identity.
- `EXPAND`: creates additional query or candidate variants with provenance.
- `TRANSFORM`: changes candidate representation while preserving lineage.
- `GENERATE`: consumes final retrieval context but is excluded from retrieval-quality claims unless explicitly analyzed.

Unsupported execution semantics fail configuration validation. Observe-only custom operators may use a namespaced custom type with declared lineage behavior; they are not silently treated as rerankers.

### 4.6 Evidence and diagnostics

Candidate transitions are the primary diagnostic source. Snapshot-order heuristics are used only when transition evidence is unavailable and are labeled accordingly.

The diagnostic engine distinguishes:

- corpus/qrel identity failure;
- source retrieval miss;
- branch-only retrieval and missing branch contribution;
- fusion loss;
- filter removal;
- gate exclusion;
- reranker loss;
- truncation below an explicit evaluation cutoff;
- final ranking failure at the requested metric cutoff;
- execution error, timeout, or incomplete capture.

Each diagnostic result includes method ID/version, evidence class, supporting operator/candidate IDs, cutoff, confidence limitations, and requirements for stronger evidence.

### 4.7 Dashboard application model

The dashboard uses a global URL-addressable context containing database, service, run, time window, cohort, and filters. Primary pages remain Home, Runs, Compare, Queries, Production, and Test Sets.

Production subviews are routes. Trace selectors are replaced by searchable trace/cohort controls and topology-variant summaries. Evaluation-to-production matches are aggregated by variant and evidence before exposing individual traces.

Compare explicitly separates:

- statistical detectability;
- practical effect size;
- power/sample sufficiency;
- multiplicity-adjusted validity;
- release-decision eligibility.

Generated Test Set queries expose stable identity, scenario, source evidence, generation method/version, transformation parameters, label class, and validation state.

### 4.8 Retrieval-analysis products

All new analysis surfaces use shared typed findings and cohort filters.

1. **Router/gate analysis:** traffic, decision distribution, labeled confusion matrix where ground truth exists, per-route coverage/quality, skipped-branch outcomes, and route drift.
2. **Branch contribution:** overlap, unique contribution, relevant-document contribution, fusion gain, and observational branch-removal estimates. Counterfactual claims require replayable evidence.
3. **Score/threshold analysis:** per-operator distributions, relevant/non-relevant calibration where labels exist, normalization diagnostics, and threshold sensitivity.
4. **Latency critical path:** p50/p95/p99 wall-clock, operator-sum, and critical-path timing with parallel/serial decomposition. Queue/network/model/storage attribution appears only when captured.
5. **Corpus/index health:** freshness, version coverage, missing qrels, duplicates, chunk coverage, ACL/filter effects, shard/selectivity data, and unavailable states.
6. **Ground-truth health:** judgment coverage, disagreement, unjudged result rate, label provenance/version drift, and a durable audit queue.
7. **Instrumentation health:** expected/observed operators, stable topology, trace/candidate coverage, sampling, drops, serialization failures, truncation, and exporter health.
8. **Saved cohorts and regression checks:** persisted filters, pinned baselines, scheduled local checks, and evidence-backed alerts. External notification delivery is outside the initial scope unless a connector is explicitly configured.



## 5. Data flow

1. `integrate plan` discovers the host project and produces a reviewable plan.
2. The engineer or agent resolves all required ambiguous mappings.
3. `integrate apply` patches observation boundaries and writes the manifest.
4. The host pipeline executes normally; spans capture stable operator and candidate transitions.
5. Completed traces enter the bounded telemetry queue.
6. The exporter normalizes, redacts, batches, and persists traces while recording capture health.
7. `integrate verify` compares observed traces with the manifest across representative scenarios.
8. Evaluation and Production APIs derive typed metrics/findings from the unified store.
9. Dashboard routes query the same evidence contracts with global context and cohorts.
10. Release checks validate source, installed wheel, external fixtures, live dashboard behavior, and documentation consistency.



## 6. Failure and safety behavior

- Discovery uncertainty is explicit; low-confidence required mappings block apply.
- Patch precondition mismatch blocks apply without partial mutation.
- Apply records every changed file and supports reversal from the plan record.
- Manifest/schema mismatch fails verification with actionable remediation.
- Queue overflow follows the configured drop policy and increments counters.
- Serialization/redaction/export failures are contained and observable.
- Shutdown flush honors a fixed deadline and reports unflushed traces.
- Missing labels suppress quality/calibration/confusion claims.
- Missing timing components suppress component attribution.
- Missing candidates suppress causal document-loss diagnoses.
- Incomplete graph coverage cannot return a ready status.
- Remote dashboard exposure requires an explicit host setting and displays a security warning when unauthenticated.



## 7. Deletion and consolidation policy

The implementation plans will identify and delete:

- V1 trace classes, recorder paths, tables, endpoints, and tests;
- `wire` and `bootstrap_project` public commands/tools;
- deprecated command aliases and warning-only wrappers;
- legacy public product terminology and routes;
- generic examples that contradict the V2 API;
- separate production trace semantics;
- stale planning/status claims superseded by this program.

Deletion occurs in the same task that replaces the behavior, so the repository never maintains two competing public paths.

## 8. Testing strategy



### Contract tests

- CLI and MCP return the same typed integration results.
- Trace and storage schemas round-trip across SQLite and PostgreSQL.
- Production traces work without run IDs; evaluation traces work with run IDs.
- Operator IDs/topology are stable across repeated scenarios.
- Every finding declares evidence and unavailable behavior.



### Integration fixtures

- Simple callable retriever.
- FastAPI hybrid DAG with intent gate, sparse/dense branches, fusion, filter, and reranker.
- LangChain callback integration.
- LlamaIndex callback integration.
- Custom candidates with non-JSON-native metadata.
- Queue overflow, exporter outage, shutdown deadline, and redaction scenarios.



### Diagnostic fixtures

- source miss, fusion loss, filter loss, gate exclusion, reranker loss, truncation, final ranking failure, branch-only contribution, error, timeout, and incomplete capture.
- Labeled and unlabeled variants prove that unsupported claims remain unavailable.



### Dashboard tests

- Route and deep-link tests for every primary/subview state.
- Cohort/filter serialization and restoration.
- Topology-variant aggregation and trace drill-down.
- Evidence/unavailable copy contracts.
- Analysis API/UI contract tests with positive and insufficient-evidence fixtures.
- Live browser walkthrough against representative demo databases.



### Release gates

- full supported Python test matrix;
- UI unit tests and production build with bundle budgets;
- wheel build and clean-environment installation;
- external fixture integration through plan/apply/verify;
- CLI/MCP parity tests;
- documentation command/link validation;
- clean repository scan for prohibited legacy/deprecated public terms;
- live dashboard verification with no uncaught console or API errors.



## 9. Delivery and release sequence



### Milestone A: Trustworthy integration foundation

Workstreams 1 and 2 complete. One integration contract and one trace/store model exist. Default FastAPI and production visibility blockers are closed.

### Milestone B: Safe and faithful observation

Workstreams 3 and 4 complete. Telemetry is isolated, bounded, and graph-faithful across supported frameworks.

### Milestone C: Correct diagnosis

Workstream 5 completes. Candidate-transition diagnostics and evidence contracts pass adversarial fixtures.

### Milestone D: Scalable investigation

Workstream 6 completes. Existing workflows are deep-linkable, searchable, cohort-aware, and understandable at production scale.

### Milestone E: Retrieval intelligence

Workstream 7 completes feature-by-feature behind shared evidence contracts. A feature ships only with positive and insufficient-evidence tests.

### Milestone F: Beta release proof

Workstream 8 removes obsolete public material, validates installed artifacts and external integrations, and produces a release evidence report.

## 10. Completion definition

The remediation program is complete only when:

- every audit issue maps to a closed implementation task and passing acceptance test;
- one-step integration is demonstrated on the complex FastAPI hybrid fixture;
- verification proves stable topology and candidate fidelity;
- production capture remains safe under exporter failure and queue overflow;
- all dashboard states are accurate, evidence-aware, and scalable;
- all eight analysis areas expose factual supported/unavailable results;
- no deprecated or legacy public surface remains;
- the clean installed package passes the full release gate;
- README, PyPI content, CLI help, MCP descriptions, and live behavior agree.

