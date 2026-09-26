# Getting started

This walkthrough runs the whole retobs loop on deterministic demo data in about ten minutes, then
points it at your own pipeline. No API keys, models, or network access are needed for the demo.

## 1. Run the demo

```bash
pip install "retrieval-observatory[dashboard]"
retobs demo
retobs serve --db .retobs/demo/results.db
```

`retobs demo` evaluates a small hybrid pipeline (dense and lexical lanes, a recency filter,
rerankers, RRF fusion, a gated expansion, a context selector) on three judged queries, twice: a
baseline whose recency filter uses `min_score: 0.85`, and a validation run with it repaired to
`0.30`. It writes `.retobs/demo/demo_manifest.json` with both run IDs and copies the release
policy next to it, then prints the exact `compare`, `inspect-document`, and `inspect-query`
commands for this invocation. Run IDs change on every invocation; below they are `BASELINE` and
`VALIDATION`.

`retobs serve` opens the dashboard at `http://127.0.0.1:4000` on Investigate; pick a run in the
scope bar at the top.

## 2. Find the lost document

In Investigate, choose the `golden-demo-baseline` run. The diagram shows the nine operators
that ran, with how many queries each served (`expand` served 1 of 3: the gate skipped it for the
other two). In the queries table, `q-outage` ("why is the site down") has one relevant document
missed.

Select `q-outage`, then `kb:doc-guide`. Its journey is two events: introduced by `lexical` at rank
1, removed by `recency_filter` with the recorded reason `min_score`. The dense lane never found it,
so that removal is its loss boundary. The same answer from the command line:

```bash
retobs inspect-document BASELINE kb:doc-guide --db .retobs/demo/results.db
```

The table also shows what else was delivered for `q-outage`: `kb:doc-faq`, judged nonrelevant,
and `kb:doc-news`, which has no judgment and is shown as `unjudged` rather than as a miss.
[Investigate your pipeline](investigate-your-pipeline.md) explains every column.

## 3. Audit the fix

```bash
retobs compare BASELINE VALIDATION --db .retobs/demo/results.db \
  --policy .retobs/demo/release-policy-golden-v3.yaml --artifacts artifacts/demo-audit \
  --fail-on hold-or-block-or-fail
echo $?    # 0: PASS
```

In the dashboard, open Audit, choose the two runs, and apply the same policy path. The decision is
`PASS`: final recall@3 improves by +0.33 over three paired queries and no query failed. Lineage
diagnosis is reported as blocked in the same audit, because the demo deliberately truncates one
operator's recorded output; promotion does not depend on it. See
[retrieval release decisions](retrieval-release-decisions.md).

To see what changed per document, open the validation run in Investigate with
`compare=BASELINE` on `q-outage`: `kb:doc-guide` is `Gained`, from excluded at `recency_filter` to
included at rank 2.

## 4. Your own pipeline

1. Connect it: ask your coding agent to follow the [agent runbook](../integrations/AGENT_QUICKSTART.md),
   or instrument it by hand with the [manual instrumentation guide](manual-instrumentation.md).
2. Evaluate it on judged queries:

   ```bash
   retobs evaluate app/search.py:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl \
     --corpus data/corpus.jsonl --name search --db .retobs/results.db
   retobs serve --db .retobs/results.db
   ```

3. Investigate a query with a missed relevant document, change the smallest thing the evidence
   supports, evaluate again on the same queries and judgments, and audit the two runs.

For a larger multi-stage example on a public dataset (downloads an embedding model on first run):

```bash
pip install "retrieval-observatory[dense,dashboard]"
retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_scifact.yaml
retobs serve --db .retobs/hybrid_scifact_demo.db
```

## Where to go next

- [evidence-limitations.md](evidence-limitations.md): what each outcome and each audit status can claim
- [hybrid-retrieval.md](hybrid-retrieval.md): lexical and dense lanes
- [multi-stage-reranking.md](experimental/multi-stage-reranking.md): reranking without losing recall
- [conditional-pipelines.md](experimental/conditional-pipelines.md): gated and routed pipelines
