# Concepts

## Run

A Run is one persisted evaluation: a manifest (query input identity, corpus, judgments and their
digest, evaluation unit and `k`, release identity from `--provenance`), per-query metrics, and one
trace per query and pipeline. `query_id` links a query to its Run; it never justifies joining
unrelated databases or services.

## Operators, invocations, and traces

An instrumented pipeline is a DAG of typed operators (`SOURCE`, `FILTER`, `RERANK`, `FUSE`,
`GATE`, `EXPAND`, `TRANSFORM`, `BOOST`, `GENERATE`). Each execution of an operator is an
invocation with its own id; repeated calls of one operator (a reranker used on two lanes) are
invocations of one stable `operator_id`, not separate stages. Each invocation records its actual
inputs and outputs and says how they were captured (`recorded`, `positional`, `inferred`,
`truncated`, `unavailable`). A gated operator that did not run is `SKIPPED_BY_GATE`.

## Judgments and entities

A judgment grades one entity for one query. Entities are namespaced (`kb:doc-guide`) at a unit
(`document` or `chunk`). A missing judgment is `unjudged`, never nonrelevant. Chunk results are
scored against document judgments only through an explicit chunk map. See
[evidence limitations](guides/evidence-limitations.md).

## Journeys and outcomes

A journey is one entity's ordered events through one query's trace (`introduced`, `retained`,
`promoted`, `demoted`, `removed`, `recovered`, `transformed`, `unknown`), each labeled recorded or
inferred. Its outcome at the evaluated boundary is one of `relevant_delivered`,
`relevant_excluded`, `retained_below_cutoff`, `not_observed`, `judged_nonrelevant`, `unjudged`,
or `insufficient_evidence`. The loss boundary is the last recorded removal on the path to that
boundary. Journeys are stored as investigation rows (schema v3) so the dashboard, CLI, SDK, and
MCP read the same answer. See [investigate your pipeline](guides/investigate-your-pipeline.md).

## Integration readiness

An integration plan declares operators, input and output mappings, the final boundary, identity,
judgments, and scenarios. Verification reports eight capabilities as `ready`, `partial`, or
`unavailable` from observed traces, and persists an integration record that Connect shows.
Declared instrumentation without observation is not ready.

## Release audit

`retobs compare` with a local v3 policy produces one `audit-1` release audit: compatibility of
the two Runs, each declared check with its paired interval and tolerance, slices, the failure-rate
cap, and changed queries linked into Investigate. The decision is `PASS`, `HOLD`, `BLOCK`, or
`FAIL`, with `BLOCK` > `FAIL` > `HOLD` > `PASS` precedence. Without a policy the decision is
`HOLD`. See [retrieval release decisions](guides/retrieval-release-decisions.md).

## Instrumentation health

Telemetry health reports accepted and exported traces, sampling, queue drops, serialization
failures, retries, and permanent export failures. It explains capture limits without changing
application responses.

## Evidence classes

See [evidence and trust](EVIDENCE_AND_TRUST.md) for the `measured`, `statistical`, `heuristic`,
`inferred`, and `unavailable` labels and for latency definitions.
