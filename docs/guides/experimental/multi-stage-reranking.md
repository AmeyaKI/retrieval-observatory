# Multi-stage reranking: precision without losing recall

Rerankers improve top-k ordering but can push documents that first-stage retrieval found below
the cutoff, or out of the list entirely. The risk is a reranker that raises nDCG on average while
quietly losing relevant documents on a subset of queries.

## Locate it per document

In [Investigate](../investigate-your-pipeline.md), filter a Run to `outcome=relevant_excluded`
and select the reranker node in the diagram. Each remaining row is a relevant document the
reranker received; its journey shows it `introduced` by a retriever and then `demoted` or
`removed` at the reranker, with the reason the reranker recorded (for example a `top_k` cut,
recorded as `truncated`). A document still in the output but ranked below `k` is
`retained_below_cutoff`, not removed.

## Decide with an audit

Compare the run with and without the reranker change under a policy that guards recall at the
final boundary as well as nDCG (`target: final_retrieval`), so a precision gain cannot hide a
recall loss. See [retrieval release decisions](../retrieval-release-decisions.md).

## Common changes to test

- Give the reranker a larger input `k`.
- Cap how far the reranker can demote first-stage hits.
- Route only some queries to the reranker (see [conditional-pipelines.md](conditional-pipelines.md)).
