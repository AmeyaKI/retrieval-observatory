# Start

See the whole loop on deterministic data first (no models, network, or keys):

```bash
pip install "retrieval-observatory[dashboard]"
retobs demo
retobs serve --db .retobs/demo/results.db
```

Then point the same three steps at your own pipeline.

1. **Connect.** `pip install retrieval-observatory`, then ask your coding agent to connect retobs
   to your retrieval pipeline (the [agent runbook](integrations/AGENT_QUICKSTART.md) is the
   procedure it follows), or run the reviewed sequence yourself:

   ```bash
   retobs integrate . --phase plan --output retobs/integration-plan.json
   retobs integrate . --phase plan --plan retobs/integration-plan.json --output retobs/integration-plan.json
   retobs integrate . --phase apply --plan retobs/integration-plan.json
   retobs integrate . --phase verify --db .retobs/results.db
   ```

   Review the plan between the two plan calls. Verify reports eight capabilities as `ready`,
   `partial`, or `unavailable` from real traces, never from the patch alone.

2. **Investigate.** Evaluate the instrumented entrypoint on judged queries and open the Run:

   ```bash
   retobs evaluate app/search.py:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl \
     --corpus data/corpus.jsonl --name search --db .retobs/results.db
   retobs serve --db .retobs/results.db
   retobs inspect-document RUN_ID namespace:doc-id --db .retobs/results.db
   ```

3. **Audit.** Compare a baseline and a candidate Run under a local policy:

   ```bash
   retobs compare BASELINE CANDIDATE --db .retobs/results.db --policy retobs/release-policy.yaml \
     --artifacts artifacts/ --fail-on hold-or-block-or-fail
   ```

The dashboard is loopback-only and unauthenticated by default. Continue with the
[workflow](WORKFLOW.md), [investigate your pipeline](guides/investigate-your-pipeline.md),
[retrieval release decisions](guides/retrieval-release-decisions.md), and the
[integration support matrix](INTEGRATIONS.md). Upgrading from 0.6: see
[migrating to focused retobs](guides/migrating-to-focused-retobs.md).
