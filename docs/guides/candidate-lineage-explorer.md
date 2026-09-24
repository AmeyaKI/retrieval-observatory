# Candidate lineage

The per-query candidate view is now the **Investigate** workspace. It shows, for a Run, each
query's candidates, each document's recorded journey through the operators that ran, its final
outcome at the evaluated boundary, and the loss boundary when a relevant document was not
delivered. Baseline/candidate lineage comparison is Investigate with `compare=BASELINE`.

- Walkthrough on the demo: [investigate your pipeline](investigate-your-pipeline.md)
- What the outcomes can and cannot claim: [evidence limitations](evidence-limitations.md)
- Old `#/runs/...` links and retired pages: [migrating to focused retobs](migrating-to-focused-retobs.md)

The outcome vocabulary changed with the rebuild. The current outcomes are `relevant_delivered`,
`relevant_excluded`, `retained_below_cutoff`, `not_observed`, `judged_nonrelevant`, `unjudged`,
and `insufficient_evidence`.

All inspection stays local to the configured database and the loopback dashboard. Redaction
happens before persistence; a preview that was not captured cannot be recovered. Review
artifacts before sharing them.
