# Evidence and trust

## Evidence classes

| Class | Meaning |
|---|---|
| `measured` | Directly persisted execution, candidate, qrel, metric, or joined trace evidence. |
| `statistical` | A declared procedure with paired sample count, effect, correction, power, and threshold. |
| `heuristic` | A rule/proxy whose method and threshold are shown. |
| `inferred` | A conclusion derived from incomplete evidence and labeled as such. |
| `unavailable` | Evidence is missing or the operation is unsupported; no numeric substitute is emitted. |

## Latency semantics

- **Wall clock**: elapsed query execution time, including concurrent waves and orchestration.
- **Critical path**: sum of operator durations on the longest fired dependency path.
- **Operator sum**: sum of fired operator durations; it can exceed wall time under concurrency.

Cached operators retain cache status and do not masquerade as normal execution. Failed, timed-out, and cancelled attempts retain partial traces and last-known outputs.

## Recorded, inferred, and unknown transitions

A candidate's transition at an operator is `recorded` when that operator's own boundary was captured, `inferred` when retobs reconstructed it (inputs from parent outputs, a rank cutoff from recorded ranks) and says so, and `unknown` when the boundary was truncated or not captured; no removal reason is asserted for an `unknown` exit. A loss boundary is the last recorded removal on the path, a descriptive fact rather than a causal effect. Counterfactual replay was retired in 0.7.0; historical records may still carry the `replayed` evidence class. See [evidence limitations](guides/evidence-limitations.md).

## Comparison rules

Missing required identity is unknown, never equal. Invalid comparisons cannot name a winner or pass a gate. Valid paired results report candidate-minus-baseline effect, p-value, BH-corrected q-value, practical threshold, paired `n`, power state, and decision reason.

## Release-policy evidence scopes

Release policies are local, versioned YAML files. Schema v3 names each check with a semantic selector (`target: final_retrieval | query | operator:<id>`) resolved against both Runs before evaluation, and slices with exact values on top-level query metadata fields. Policies do not accept expressions, regular expressions, SQL, or executable policy code.

Promotion readiness and lineage-diagnosis readiness are separate claims. Missing lineage evidence blocks the `lineage_diagnosis` claim but does not block promotion unless the policy requires lineage for the decision (`evidence.require_lineage_for_decision` in v3). `PASS` means the recorded evidence supports promotion under the declared policy; `HOLD` means valid evidence is inconclusive; `BLOCK` means policy-required evidence is absent or invalid; and `FAIL` means valid evidence proves a regression beyond a declared budget. A `PASS` does not establish universal safety, deployment readiness, or a causal explanation.

## Diagnostic limits

A valid relevant document missed by retrieval is a miss, not a corpus/qrel identity mismatch. `qrel_absent_from_corpus` (the label the runner emits; older dashboards spelled it `qrel_not_in_corpus`) is reserved for an actually absent qrel document ID. Trace quality outside an evaluated Run is unavailable: without judgments there is no delivered or missed relevant document to report.
