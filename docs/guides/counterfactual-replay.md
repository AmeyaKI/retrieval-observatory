# Counterfactual Replay — how attribution actually works

retobs answers "what did this operator contribute?" by **replaying the pipeline without that
operator** and measuring the difference against ground truth. This guide explains the
mechanism so you can trust — and audit — every attribution number.

## The idea

For an operator `O` in a query's trace, `without_operator(trace, O)`
(`retrieval_observatory/tracing/replay.py`) constructs a counterfactual trace as if `O` had
not run, then re-scores the final results against the qrels. The contribution of `O` is:

```
contribution(O) = metric(final_with_O) − metric(final_without_O)
```

averaged over all queries where `O` fired, with a bootstrap confidence interval and a
paired significance test — `operator_marginal_contribution` in
`retrieval_observatory/tracing/attribution.py`. That function corrects p-values
(Benjamini–Hochberg) across the *segments of one operator* only. When several operators are
compared side by side, `operator_marginal_contributions(traces, op_ids, ...)` (plural) runs
them all and applies one BH correction across every (operator, segment) pair, so the
q-values account for every comparison shown.

## Replay tiers — honesty about what can be replayed

Not every operator can be replayed exactly. Each carries a **replay policy**:

- `EXACT` — the counterfactual is deterministic (e.g. removing a filter or re-running RRF
  fusion over the remaining arms). The delta is exact.
- `OBSERVED_ABLATION` — the operator is non-deterministic (e.g. a neural reranker); retobs
  reuses observed scores rather than calling the model again. The delta is an estimate.
- `NOT_REPLAYABLE` — the counterfactual cannot be constructed faithfully; retobs reports the
  result as `indeterminate` rather than a fabricated number.

## The strict rule — no fabricated downstream decisions

Replay is strict. Removing `O` changes what its descendants receive, and retobs only ever
reuses what those descendants were *observed* to do:

- A **FUSE** child is recomputed exactly: reciprocal-rank fusion is re-run over its arms,
  with `O`'s arm dropped (when `O` is a source) or substituted by `O`'s replacement (when `O`
  is a filter, reranker, boost, expansion, gate or transform). The constant is read from
  the span's `params["rrf_k"]` (older traces wrote `params["k"]`; both are honoured).
- A **SOURCE** child is left untouched — a source's outputs do not derive from parent
  candidates; the edge is a control dependency such as a gate.
- Any **other** child keeps its recorded outputs, filtered to the documents that still flow
  into it, with ranks renumbered `1..n`. If the counterfactual would hand the child a
  document it *never observed* in its recorded inputs, its decision on that document is
  unknown. retobs does not guess: the whole replay is `indeterminate`
  (`status="indeterminate"`, `evidence_class="unavailable"`, with a reason naming the child
  and how many documents it never saw). Removing a filter whose reranker only ever scored
  the filtered set is the canonical example.
- The rule applies transitively: a recomputed fusion that would surface a document to a
  reranker that never scored it is also `indeterminate`.
- Removing a **source** touches only its descendants. A document another surviving arm also
  found is kept; unrelated branches are never modified.

`simulate_without_operator` returns the typed result; the lower-level `without_operator`
raises `ValueError` for the indeterminate case.

## Replay assumptions — inspect, don't trust

Every counterfactual is built by a specific strategy. `replay_assumptions(trace, op_id)`
returns a `ReplayAssumptions` object naming the strategy and its caveats, for example:

- `fuse_rrf_recompute` — fusion re-run over remaining arms with the same `rrf_k`; per-arm
  scores reused.
- `rerank_passthrough_inputs` — the reranker's input ordering is restored (multi-parent
  inputs concatenated in parent order, de-duplicated); downstream operators keep their
  observed decisions on those documents, or the replay is indeterminate.
- `boost_restore_pre_boost` — pre-boost scores restored from `score_components`.

In the dashboard, the **candidate flow** panel surfaces these assumptions wherever a drop is
explained, so you always know how the counterfactual was made.

## Where you see it

- **Per-stage attribution** grid — contributions with CI, p-value, BH-corrected q-value.
- **Candidate flow** — per-document, the replay assumptions behind a drop.
- **Finding simulation** — `simulate_operator_removal`
  (`retrieval_observatory/experimental/advisor/simulate.py`) reuses the exact same machinery to
  *estimate the impact of a change before you make it*.
