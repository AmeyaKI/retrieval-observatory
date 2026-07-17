# Concepts

## Run and query evidence

A Run is a persisted evaluation with manifest identity, queries, labels, metrics, and complete or partial traces. `query_id` links a scoped query to its Run; it does not justify joining unrelated databases, services, or time windows.

## Operators and candidates

An observed retrieval pipeline is a DAG of typed operators. Candidate origins and transitions record what an integration emitted; missing inputs, outputs, or branches remain unavailable rather than reconstructed from a diagram.

## Integration readiness

An integration plan declares operators, candidate mappings, and verification scenarios. `ready` requires observed topology, candidate, and telemetry evidence. `partially_instrumented`, `not_verified`, and `failed` name different limits and should not be treated as ready.

## Comparison and production evidence

Comparison requires compatible query, corpus, qrel, and labeling identity. Production trace summaries report sampled operational evidence; without ground-truth linkage they are not recall, ranking quality, or causal proof.

## Instrumentation health

Telemetry health reports accepted/exported traces, sampling, queue drops, serialization failures, retries, and permanent export failures. It explains capture limits without changing application responses.
