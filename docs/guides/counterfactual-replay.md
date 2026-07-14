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
paired significance test (Benjamini–Hochberg corrected across operators) —
`operator_marginal_contribution` in `retrieval_observatory/tracing/attribution.py`.

## Replay tiers — honesty about what can be replayed

Not every operator can be replayed exactly. Each carries a **replay policy**:

- `EXACT` — the counterfactual is deterministic (e.g. removing a filter or re-running RRF
  fusion over the remaining arms). The delta is exact.
- `OBSERVED_ABLATION` — the operator is non-deterministic (e.g. a neural reranker); retobs
  reuses observed scores rather than calling the model again. The delta is an estimate.
- `NOT_REPLAYABLE` — the counterfactual cannot be constructed faithfully; retobs reports the
  result as `indeterminate` rather than a fabricated number.

## Replay assumptions — inspect, don't trust

Every counterfactual is built by a specific strategy. `replay_assumptions(trace, op_id)`
returns a `ReplayAssumptions` object naming the strategy and its caveats, for example:

- `fuse_rrf_recompute` — fusion re-run over remaining arms with the same `k`; per-arm scores
  reused.
- `rerank_passthrough_inputs` — the reranker's input ordering is restored; downstream scores
  are reused, not recomputed by a real model call.
- `boost_restore_pre_boost` — pre-boost scores restored from `score_components`.

In the dashboard, the **candidate flow** panel surfaces these assumptions wherever a drop is
explained, so you always know how the counterfactual was made.

## Where you see it

- **Per-stage attribution** grid — contributions with CI, p-value, BH-corrected q-value.
- **Candidate flow** — per-document, the replay assumptions behind a drop.
- **Finding simulation** — `simulate_operator_removal`
  (`retrieval_observatory/advisor/simulate.py`) reuses the exact same machinery to
  *estimate the impact of a change before you make it*.
