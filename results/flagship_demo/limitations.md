# What this demo does not show

The flagship demo has the following limits:

- **It is not a competitive retrieval system.** Widths and models were chosen for legibility
  and cheap reruns. Every scenario compares two runs with the same components, so absolute
  quality cancels.
- **It does not show that retobs is easy to adopt.** This pipeline was built inside the retobs
  repository against its internals. Whether an agent can wire retobs into another project from
  one instruction is a separate question, tested separately, and not answered here.
- **Ground truth is positive-only.** Most retrieved documents are therefore
  `unknown_relevance`. This is not a tracing failure; it limits how much the lineage read-out
  can say. Tracing health (`lineage_incomplete`) is 0.0%.
- **One lineage requirement is unmet.** This pipeline records no document content hashes, so
  `lineage_document_identity_partial` fires and is left visible in every report. The finding
  reflects a real gap in the recorded evidence, not a reporting error.
