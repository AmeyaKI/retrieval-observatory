# Candidate Lineage Explorer

The Candidate Lineage Explorer shows the candidate paths actually recorded for a query. Its default view is a static DAG with branch labels, operational outcome counts, and a trace-qualified candidate passport. Recorded replay is optional and secondary; it replays captured events and does not re-execute the retrieval pipeline.

## Investigation path

Start from a `HOLD`, `BLOCK`, or `FAIL` guard in Compare, select an affected query, and inspect its candidate lineage. This preserves the evidence chain:

```text
release decision → guard/slice → affected query → static lineage → candidate passport
```

The passport shows the available source identity/revision, every observed route, ranks and scores, recorded or legacy-inferred exit evidence, parents, derived children, relevance state, and capture completeness. Preview text appears only when the local capture policy retained it.

## Operational outcomes

The Explorer uses retrieval-operational language:

- `relevant_retained`
- `irrelevant_removed`
- `irrelevant_retained`
- `relevant_lost_upstream`
- `relevant_dropped_at_stage`
- `unknown_relevance`
- `lineage_incomplete`

It does not label an observed irrelevant candidate removed mid-pipeline as a true negative. Production candidates without joined validated labels remain `unknown_relevance`. A partial trace without complete output or exit evidence remains `lineage_incomplete`; absence from a truncated output is not treated as a recorded drop.

## Baseline/candidate lineage diff

Lineage diff aligns candidates only when query ID, logical chunk identity, and document revision or content hash match. Stage-aligned changes additionally require compatible recorded topology. Valid diffs may report newly surfaced, newly dropped, newly retained, rank-shifted, branch-changed, or exit-changed candidates.

When document revision or topology semantics do not align, the diff is `BLOCK` and shows the two recorded paths side by side. A changed path is an investigation clue, not a causal claim.

## Privacy and limits

All inspection remains local to the configured database and loopback dashboard by default. Redaction happens before persistence; omitted previews cannot be recovered by the Explorer. Restrict database access, choose retention and sampling deliberately, and review artifacts before sharing them.

Stage loss accounting reports recorded counts. It may suggest where to inspect, but it does not recommend automatic tuning or establish why a metric changed.
