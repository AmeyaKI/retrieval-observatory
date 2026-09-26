# Retrieval debugging workflow

1. **Connect.** Plan, review, re-plan, apply, run the scenarios, and verify
   (`retobs integrate . --phase verify --db .retobs/results.db`). Verification reports eight
   capabilities from observed traces; a `partial` capability is a stated limitation, not a
   failure. See the [agent runbook](integrations/AGENT_QUICKSTART.md).
2. **Evaluate.** Run the instrumented entrypoint on judged queries with `retobs evaluate`. The
   Run records each operator's actual inputs and outputs per query and is indexed for
   investigation when it finishes.
3. **Investigate.** Open the Run in `#/investigate`. Start from a query with a relevant document
   missed, select the document, and read its recorded transitions and loss boundary. Check its
   capture labels before trusting a removal: `recorded`, `inferred`, or `unknown`. See
   [investigate your pipeline](guides/investigate-your-pipeline.md).
4. **Change one thing.** Make the smallest change the evidence supports and evaluate again on the
   same queries, corpus, and judgments.
5. **Audit.** `retobs compare BASELINE CANDIDATE --policy retobs/release-policy.yaml --artifacts artifacts/`
   returns `PASS`, `HOLD`, `BLOCK`, or `FAIL` under the declared policy. From Audit, open each
   changed query in Investigate with `compare=BASELINE` to see which documents were gained or
   lost and where. See [retrieval release decisions](guides/retrieval-release-decisions.md).

An audit's promotion readiness and its lineage readiness are separate claims: a comparison can
support promotion while partial capture blocks lineage diagnosis. Document-level judgments score
chunk results only through an explicit chunk map. See
[evidence limitations](guides/evidence-limitations.md).
