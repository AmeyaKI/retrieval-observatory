# Concepts

## Run and query evidence

A Run is a persisted evaluation with manifest identity, queries, labels, metrics, and complete or partial traces. `query_id` links a scoped query to its Run; it does not justify joining unrelated databases, services, or time windows. `QueryEvidence` is the scoped document CLI, SDK, MCP, and the dashboard render for one `(db, run, query)`.

## Operators and candidates

An observed retrieval pipeline is a DAG of typed operators. Candidate origins and transitions record what an integration emitted; missing inputs, outputs, or branches remain unavailable rather than reconstructed from a diagram. Trace envelopes use `schema_version=1`; candidate lineage fields use an independent lineage schema version.

## Integration readiness

An integration plan declares operators, candidate mappings, and verification scenarios. `retobs integrate --phase verify` reports `ready`, `partially_instrumented`, or `failed` from observed topology, candidate, and telemetry evidence. Declared instrumentation without observation is not ready.

## Comparison, release decisions, and production evidence

Comparison requires compatible query, corpus, qrel, and labeling identity. With a local release policy, `retobs compare` returns one of `PASS`, `HOLD`, `BLOCK`, or `FAIL` under that policy's budgets and slices. Without a policy, comparison fields remain available but the release decision is `HOLD`.

Promotion readiness and lineage-diagnosis readiness are separate claim scopes. Document-level qrels require an explicit, complete qrel-to-chunk mapping before retobs makes chunk-level relevance claims. Production trace summaries report sampled operational evidence; without ground-truth linkage they are not recall, ranking quality, or causal proof.

## Candidate lineage

Candidate lineage is a static, evidence-aware view of recorded routes, exits, ranks/scores when present, and operational outcomes. A candidate passport aggregates that evidence for one identity. Baseline/candidate lineage diffs align only when query, document revision, and topology evidence agree—or when the policy declares exact one-to-one equivalent stages. Otherwise retobs keeps side-by-side recorded paths and blocks the diff claim.

## Test Sets and findings

Test Sets are corpus-generated stress queries with scenario typing and manifest fingerprints (`retobs testsets`). Findings and recommendations are embedded inside Runs, Compare, and Queries; they are planning aids over recorded diagnostics, not a separate product surface.

## Instrumentation health

Telemetry health reports accepted/exported traces, sampling, queue drops, serialization failures, retries, and permanent export failures. It explains capture limits without changing application responses.

## Evidence classes

Use [evidence and trust](EVIDENCE_AND_TRUST.md) for `measured`, `statistical`, `replayed`, `heuristic`, `inferred`, and `unavailable` semantics, latency definitions, and replay limits.
