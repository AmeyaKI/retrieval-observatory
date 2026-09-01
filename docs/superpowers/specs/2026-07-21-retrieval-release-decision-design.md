# RetObs Retrieval Release Evidence and Candidate Lineage Design

## Portfolio and product context

RetObs is a local-first, privacy-conscious reliability layer for retrieval pipelines. The primary user is an ML/AI platform engineer who must decide whether a retrieval change is safe to promote across customer-facing RAG systems, then later explain that decision. The project is a flagship portfolio artifact for ML engineering, AI engineering, ML infrastructure, and FDE roles. It must demonstrate production judgment: measurable contracts, safe integration, reproducible statistical decisions, honest limitations, and a useful investigation workflow.

The career story this project supports is: "I build reliable production ML/LLM systems—especially retrieval/RAG—combining evaluation, serving, and decision tooling for real customer workflows." RetObs must not imply adoption, deployed users, superior performance, or external validation that the project cannot evidence.

## Market boundary and defensible contribution

RetObs is not another generic RAG evaluator, answer evaluator, leaderboard, workflow builder, or broad observability suite. Langfuse, Phoenix, LangSmith, MLflow, Braintrust, Evidently, Ragas, DeepEval, and research tools already cover broad combinations of traces, datasets, experiment comparison, output scoring, dashboards, and CI thresholds. RetObs should interoperate with such systems where practical rather than try to replace them.

The defensible contribution is a narrow, opinionated workflow:

> RetObs is a local-first evidence-control plane for retrieval changes. It determines whether the recorded evidence supports promotion, hold, block, or failure under an explicit policy, then exposes the observed candidate paths that explain an affected retrieval result.

This is an engineering composition, not a claim of first-ever or research novelty. Existing tools can often reproduce portions with custom metadata or code. RetObs earns its place by making the following behavior first-class and auditable:

1. compare run identity and capture completeness before trusting metric deltas;
2. distinguish absent/invalid evidence (`BLOCK`) from valid but inconclusive evidence (`HOLD`);
3. join a release decision to retrieval-stage candidate lineage without inventing relevance, causes, or exit reasons;
4. preserve local-first operation, privacy controls, reviewed/reversible instrumentation, and CI-ready artifacts.

## Approved release-decision contract

The canonical command remains:

```bash
retobs compare BASELINE CANDIDATE --policy retobs/release-policy.yaml
```

There is no new `decide` command. CLI, SDK, MCP, API, dashboard, Markdown, HTML, JSON, and CI consume one canonical `ReleaseDecision` payload.

`PASS` means the candidate is demonstrably non-inferior for every policy-critical guard within its declared budget. Improvement is not required.

| Status | Meaning |
|---|---|
| `PASS` | Required promotion evidence is valid and every required paired interval proves non-inferiority. |
| `HOLD` | Promotion evidence is valid but cannot prove pass or fail: for example, an underpowered slice or interval crossing a budget. |
| `BLOCK` | A policy-required promotion evidence condition—identity, label, coverage, topology, or telemetry—is absent or invalid. |
| `FAIL` | Valid promotion evidence proves a policy-critical aggregate or declared-slice regression beyond its budget. |

`PASS` never means universally safe, causally explained, or automatically ready to deploy. It means the recorded evidence supports promotion under the versioned policy.

### Claim-scoped evidence readiness

Promotion and diagnosis are different claims. A run may have sufficient final-output evidence for a promotion decision while lacking the stage transitions needed to explain a reranker loss. RetObs therefore returns one overall `ReleaseDecision` plus named evidence readiness for these scopes:

| Scope | Question | Missing evidence effect |
|---|---|---|
| `promotion` | May the declared release policy promote this candidate? | `BLOCK` only when the policy requires that evidence. |
| `aggregate_or_slice_evaluation` | Is a stated metric/slice comparison valid? | `BLOCK` or `HOLD` according to the evidence condition. |
| `lineage_diagnosis` | Can RetObs attribute observed candidate loss/survival to a stage? | Diagnostic readiness is `BLOCK`; do not necessarily block promotion. |
| `lineage_diff` | Can RetObs compare paths across baseline and candidate? | Show separate paths; do not make a causal-looking diff. |
| `production_trace` | Can live capture support a production observation claim? | Mark the claim unavailable or partial. |

The report must present these separately. A policy can deliberately require lineage readiness for promotion, but it is never an implicit universal requirement.

## Data flow

```text
Reviewed integration / standards adapter
  → versioned run identity + trace capture health
  → candidate-lineage contract (per-query DAG)
  → evidence profile and policy assessment
  → paired aggregate and declared-slice intervals
  → PASS / HOLD / BLOCK / FAIL release decision
  → affected query → static lineage graph → candidate passport
```

## Release policy limits

Policies are local, versioned files. They are intentionally constrained:

- metric selectors are exact existing canonical metric keys;
- query slices are exact literals on persisted top-level query metadata;
- no expressions, regexes, SQL, arbitrary Python, or post-hoc slice mining;
- every policy artifact includes an ID, schema version, digest, declared evidence requirements, statistics, metrics, and slices;
- reports display policy/baseline changes so a pull request cannot silently loosen a budget and change the candidate simultaneously.

Policies declare evidence separately for promotion and lineage diagnosis. They may require corpus/index identity, labels, telemetry limits, candidate-identity continuity, stage input/output coverage, recorded exit reasons, and topology compatibility.

## Statistical contract

Quality and mean-like operational metrics use paired query bootstrap resampling of candidate-minus-baseline deltas. Percentile latency uses paired-index resampling and recomputes the declared quantile on every resample; RetObs must never label a mean delta as `p95` or `p99` latency.

The policy family-wise alpha is adjusted across declared aggregate and slice guards before intervals are built. Existing paired-test p-values and BH q-values remain diagnostic context, not the promotion-pass criterion.

For higher-is-better metrics, the lower interval bound must be at least `-max_regression` to pass and the upper bound below that boundary fails. The inverse applies to lower-is-better metrics. Insufficient paired observations produce `HOLD`; a required unavailable condition produces `BLOCK`.

The implementation must expose paired sample count, seed, resample count, confidence level, interval method, and adjusted confidence level. It must document that a narrow offline test set, faulty labels, or unrepresentative slices can still limit a decision.

## Candidate Lineage Contract

Candidate Lineage Explorer is a retrieval-specific, evidence-aware debugger for complex retrieval DAGs. It evolves the existing candidate-flow workspace, candidate transitions, query-detail candidate table, and recorded replay UI; it is not a second generic trace viewer.

### Required model semantics

A trace records a versioned retrieval DAG of operators. Candidate lineage must preserve:

- stable `candidate_id` and `logical_chunk_id`, with legacy `doc_id` mapped only when it is genuinely stable;
- source document ID, document revision/content hash, chunk offsets, and optional redacted preview;
- per-query, run, pipeline, topology, branch, and stage identity;
- ordered input and output candidate sets for each operator;
- ranks, scores, score type/model, and score components at each stage;
- explicit parent candidate IDs for one-to-many expansion, many-to-one fusion, deduplication, and transformed/derived candidates;
- explicit stage decision and structured exit reason where instrumentation supplies it;
- a distinction between recorded, inferred-from-legacy, partial, and unavailable evidence;
- capture completeness: candidate identity continuity, stage input/output availability, exit-reason availability, topology/edge availability, candidate truncation, sampling, redaction, and serialization loss.

The model must represent paths as a DAG. A candidate may have multiple parents and multiple observed routes. It must not flatten branches into a fabricated single path or infer an exit merely because a trace was partially captured.

### Operational outcome terminology

Do not use `true negative` for irrelevant items that were retrieved and later removed. Corpus-wide true negatives are neither observable nor useful in this UI. Replace the existing TP/FP/FN/TN labels with:

| Outcome | Evidence requirement |
|---|---|
| `relevant_retained` | Valid relevance evidence and final-context membership. |
| `irrelevant_removed` | Observed candidate, validated irrelevance, and recorded removal. |
| `irrelevant_retained` | Validated irrelevance and final-context membership. |
| `relevant_lost_upstream` | Valid qrel-to-chunk mapping and sufficient observed retrieval-entry coverage. |
| `relevant_dropped_at_stage` | Valid relevance evidence, observed stage input/output, and recorded or clearly marked inferred exit. |
| `unknown_relevance` | No qrels or validated relevance evidence. |
| `lineage_incomplete` | Candidate/path presence or exit cannot be determined from capture. |

Production traces commonly have `unknown_relevance`. RetObs must show their routes, ranks, scores, and recorded exits while refusing TP/FP/FN-style conclusions. Document-level qrels must not silently become chunk-level qrels; the mapping and coverage are evidence fields.

## Candidate Lineage Explorer UX

The primary investigation path is:

```text
Release decision → failed/held guard → declared slice → affected query
  → Candidate Lineage Explorer → selected candidate passport
```

The default is a static, inspectable DAG. Nodes are retrieval stages; edges represent recorded candidate transitions. Aggregate mode uses widths/counts, while a selected candidate highlights every observed route. The user can filter by branch, stage, source, outcome, relevance state, and evidence completeness.

The candidate passport shows text/metadata subject to redaction, source document/revision, all observed routes, input/output rank and score at each stage, decision/exit reason with evidence class, lineage parents/derived children, and baseline/candidate differences when valid.

Stage loss accounting shows relevant retained, relevant dropped, irrelevant retained, irrelevant removed, unknown relevance, and incomplete lineage by stage for a query or selected declared slice. It suggests where to investigate only when the statement is directly supported by recorded counts; it does not propose automatic tuning or claim causality.

Recorded replay/animation is optional, scrubbable, and clearly labeled as replay of capture—not re-execution. It is never the only diagnostic view and must not be the product moat.

## Baseline/candidate lineage diff

The diff aligns a query and only matches candidates where stable logical chunk/document revision identity is available. It highlights newly surfaced, newly dropped, newly retained, rank-shifted, branch-shifted, and changed-exit candidates.

End-to-end release comparison may remain valid through an intended topology change. Stage-by-stage lineage comparison is not automatically valid: when stages/semantics are not aligned, RetObs renders side-by-side paths and returns `lineage_diff: BLOCK` with a precise reason. It never calls a changed route the causal source of a regression merely because it changed.

## Integration, privacy, and interoperability

RetObs retains reviewed `plan → apply → verify` integration, reversibility, redaction controls, queue/overflow configuration, sampling, and loopback dashboard binding. Source mutation is optional: standards-oriented ingestion/adapters should be preferred when OpenTelemetry/OpenInference-compatible retrieval data already exists. RetObs documents its lineage extension rather than claiming a standard provides every required field.

Raw query text, chunk previews, document IDs, and metadata remain local by default and obey existing redaction/omission controls. Reports include lineage summaries by default, not raw chunks. Detailed content is shown only in the local inspector when permitted by capture policy.

## Delivery boundaries

1. **Release foundation:** policy, run identity, evidence assessment, paired intervals, declared slices, decision artifact, CI, integration preflight.
2. **Lineage contract:** stable identity, explicit DAG parentage, recorded exit decisions, per-scope completeness, compatibility for legacy traces.
3. **Offline labeled Explorer:** static graph, candidate passport, correct operational outcomes, stage loss accounting.
4. **Run diff:** valid baseline/candidate candidate-path comparison and release-report deep links.
5. **Complex DAG and production:** routing/fusion/derived candidates, standards adapter, time-window telemetry, unknown relevance and partial capture states.
6. **Bounded guidance:** evidence-linked investigation suggestions only.

Non-goals: generic answer evaluation; a hosted collaboration/governance service; deployment control; another broad observability dashboard; unbounded dynamic policies; automatic tuning; unsupported causal claims; an animation-first product.

## Compatibility

`compare` without a policy retains existing paired-comparison fields but returns release `HOLD` with the reason that a release policy is required for promotion. Existing `--fail-on regression` and `regression-or-no-decision` aliases remain for one release cycle; the canonical terms are `fail` and `hold-or-block-or-fail`.

Legacy traces remain inspectable. Their candidate-history facts are marked `legacy_inferred`, `partial`, or `unavailable` as appropriate; RetObs does not reinterpret them as fully compliant lineage capture.
