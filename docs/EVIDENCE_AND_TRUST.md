# Evidence and trust

## Evidence classes

| Class | Meaning |
|---|---|
| `measured` | Directly persisted execution, candidate, qrel, metric, or joined trace evidence. |
| `statistical` | A declared procedure with paired sample count, effect, correction, power, and threshold. |
| `replayed` | A supported counterfactual under explicit assumptions. |
| `heuristic` | A rule/proxy whose method and threshold are shown. |
| `inferred` | A conclusion derived from incomplete evidence and labeled as such. |
| `unavailable` | Evidence is missing or the operation is unsupported; no numeric substitute is emitted. |

## Latency semantics

- **Wall clock**: elapsed query execution time, including concurrent waves and orchestration.
- **Critical path**: sum of operator durations on the longest fired dependency path.
- **Operator sum**: sum of fired operator durations; it can exceed wall time under concurrency.

Cached operators retain cache status and do not masquerade as normal execution. Failed, timed-out, and cancelled attempts retain partial traces and last-known outputs.

## Replay limits

`EXACT` means all affected downstream behavior can be recomputed from recorded inputs and deterministic semantics. `OBSERVED_ABLATION` means a matching observed path supports the difference. `NOT_REPLAYABLE` yields an indeterminate result with no delta, interval, or p-value.

## Comparison rules

Missing required identity is unknown, never equal. Invalid comparisons cannot name a winner or pass a gate. Valid paired results report candidate-minus-baseline effect, p-value, BH-corrected q-value, practical threshold, paired `n`, power state, and decision reason.

## Release-policy evidence scopes

Release policies are local, versioned YAML files with exact canonical metric keys and exact values on top-level query metadata fields. They do not accept expressions, regular expressions, SQL, or executable policy code.

Promotion readiness and lineage-diagnosis readiness are separate claims. Missing lineage evidence blocks the `lineage_diagnosis` claim but does not block promotion unless the policy explicitly makes that evidence a promotion requirement. `PASS` means the recorded evidence supports promotion under the declared policy; `HOLD` means valid evidence is inconclusive; `BLOCK` means policy-required evidence is absent or invalid; and `FAIL` means valid evidence proves a regression beyond a declared budget. A `PASS` does not establish universal safety, deployment readiness, or a causal explanation.

## Diagnostic limits

A valid relevant document missed by retrieval is a miss, not a corpus/qrel identity mismatch. `qrel_not_in_corpus` is reserved for an actually absent qrel document ID. Production quality is unavailable unless explicit labels are joined.
