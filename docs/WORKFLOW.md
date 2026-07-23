# Retrieval reliability workflow

1. **Plan and integrate.** Review `retobs/integration-plan.json`; apply only that plan, then verify observed instrumentation and the local policy with `retobs integrate . --phase verify --policy retobs/release-policy.yaml`.
2. **Evaluate.** Run the baseline and candidate against the same intended query, corpus, qrel, and label identities.
3. **Compare.** `retobs compare BASELINE_RUN CANDIDATE_RUN --db .retobs/results.db --policy retobs/release-policy.yaml` returns canonical `PASS`, `HOLD`, `BLOCK`, or `FAIL`. Underpowered evidence holds; missing policy-required identity or labels block.
4. **Inspect an affected query.** Open it from Compare to preserve the decision → guard/slice → query chain. The static Candidate Lineage Explorer shows recorded routes and explicit unknown/partial evidence before optional recorded replay.
5. **Validate a change.** Make the smallest change supported by that evidence, rerun the same Test Set, and compare the validation Run with the candidate.

Production traces enrich investigation when they have a matching service/pipeline scope. They are not retrieval-quality measurements without joined ground truth.

Promotion readiness and lineage readiness are separate. Document-level qrels require an explicit, complete qrel-to-chunk mapping before RetObs makes chunk-level relevance claims. See [retrieval release decisions](guides/retrieval-release-decisions.md) and [Candidate Lineage Explorer](guides/candidate-lineage-explorer.md).
