# Multi-stage Reranking — precision without losing recall

Rerankers improve top-k ordering but can *drop relevant documents* that first-stage retrieval
found. The central risk is a reranker that raises nDCG on average while quietly hurting recall
on a subset of queries. retobs is built to catch exactly this.

## The failure mode: `reranker_drop`

The diagnostics label a query `reranker_drop` when a relevant document was present in the
first-stage candidate pool but absent from the final results after reranking. A high
`reranker_drop` rate means the reranker is trading away recall.

## Locate it per document

On an affected query, open **candidate flow** for the missed document. You will see it
introduced by the retriever, then a `dropped` event at the reranker with reason
`reranked_out`. That is direct, per-document proof — not an aggregate inference.

## Quantify it with attribution

The per-stage attribution grid shows the reranker's marginal contribution to *recall* (not
just nDCG), with a confidence interval and significance. A reranker with positive nDCG but a
significant negative recall contribution is the classic offender.

Because rerankers are non-deterministic, their replay tier is `OBSERVED_ABLATION`: retobs
restores the reranker's input ordering and reuses observed scores rather than calling the
model again. The attribution is honest about this via `ReplayAssumptions`
(see [counterfactual-replay.md](counterfactual-replay.md)).

## Before you change it: simulate

`simulate_operator_removal` estimates what removing (or bypassing) the reranker would do to
recall across the run, so you can weigh the precision/recall trade before touching config.

## Fixes retobs will suggest

- Increase the reranker's input `k` so it has more to work with.
- Cap how far the reranker can demote first-stage hits.
- Route only hard queries to the reranker (see
  [conditional-pipelines.md](conditional-pipelines.md)).
