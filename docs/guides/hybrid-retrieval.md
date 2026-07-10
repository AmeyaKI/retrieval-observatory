# Hybrid Retrieval — combining lexical and dense arms

Lexical (BM25) and dense (embedding) retrieval fail on different queries: BM25 misses
paraphrase/semantic matches, dense misses exact-term/rare-token matches. Running both and
fusing recovers queries that either alone would miss. retobs both **diagnoses when you need
hybrid** and **measures what it buys you**.

## When retobs tells you to go hybrid

The diagnostics classify failures. Two labels point straight at hybrid retrieval:

- `lexical_mismatch` — dense retrieval succeeds where BM25 fails (add a dense arm).
- `semantic_mismatch` — BM25 succeeds where dense fails (add a lexical arm).

When either exceeds threshold, the Advisor recommends adding the complementary arm, with an
estimated recall improvement and confidence (see [advisor.md](advisor.md)).

## Modeling it as an operator DAG

A hybrid pipeline is two `SOURCE` operators feeding a `FUSE` operator (reciprocal-rank
fusion). In the trace this is a genuine fan-in: the fusion node has two parents. The pipeline
architecture view renders the two lanes and the fan-in edge explicitly — it is not flattened
into a linear chain.

## Measuring the contribution of each arm

Because fusion is `EXACT`-replayable, retobs can remove one arm and re-run RRF over the
remaining arm to measure exactly what that arm contributed
(`fuse_rrf_recompute`, see [counterfactual-replay.md](counterfactual-replay.md)). The
per-stage attribution grid shows each arm's marginal recall/nDCG contribution with a
confidence interval — so you can tell whether the dense arm is actually earning its latency.

## Watching a document move

Use **candidate flow** on a query that only hybrid gets right: you will see the relevant
document introduced by one arm, fused, and surviving to the final results — the visual proof
that the second arm was necessary.
