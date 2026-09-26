# Conditional and parallel pipelines: gates, routing, and lanes

Retrieval pipelines are rarely a straight line. Queries get routed by type, some branches are
skipped, and several lanes run in parallel and fuse. retobs records these as an operator DAG
(`RetrievalTrace`), not a flat stage list.

## Gates and skipped branches

A `GATE` operator routes a query down one branch or another based on the `gate_values` recorded
in the trace. When a branch is not taken, its operators are recorded as `SKIPPED_BY_GATE` and
drawn as skipped in the Investigate diagram, not omitted. A skipped operator receives and drops
nothing, and it is excluded from the served-query count (`served 1 of 3 queries`), so a branch is
never scored as zero on queries it did not see.

With `@observe("GATE")`, a function that returns a route string (or a mapping of scalars) records
it as `gate_values`. The SDK also offers `observe_gate(gate_name, fired, gate_values, op_id=...)`.
In an integration plan, declare one scenario per route with its `route`, so verification checks
that every declared route was observed.

## Parallel lanes

Multiple `SOURCE` operators feeding a `FUSE` operator are parallel lanes; see
[parallel-retrieval.md](parallel-retrieval.md).

## Topology comes from traces

The diagram is built from executed traces (`parent_ids` on each span), never inferred from a
config when traces exist, so branching, fusion, and skipped operators appear as they ran.
