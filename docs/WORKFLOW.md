# Retrieval reliability workflow

1. **Plan and integrate.** Review `retobs/integration-plan.json`; apply only that plan, then verify observed instrumentation.
2. **Evaluate.** Run the baseline and candidate against the same intended query, corpus, qrel, and label identities.
3. **Compare.** `retobs compare BASELINE_RUN CANDIDATE_RUN --db .retobs/results.db` reports validity before any winner. Underpowered or identity-mismatched comparisons do not establish a result.
4. **Inspect a query.** `retobs inspect-query CANDIDATE_RUN QUERY_ID --db .retobs/results.db` shows only persisted query, operator, candidate, and ground-truth evidence.
5. **Validate a change.** Make the smallest change supported by that evidence, rerun the same Test Set, and compare the validation Run with the candidate.

Production traces enrich investigation when they have a matching service/pipeline scope. They are not retrieval-quality measurements without joined ground truth.
