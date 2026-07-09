# Getting Started — from install to a fixed pipeline in under an hour

This is the beginner journey. It follows the way engineers actually debug retrieval:
**run → understand → find the failure → locate the stage → improve → validate.** By the
end you will have run a benchmark, read the dashboard, debugged a failing query down to the
responsible operator, applied a fix, and confirmed it helped.

No API keys are required for the walkthrough.

---

## 1. Install and run (5 minutes)

```bash
pip install "retrieval-observatory[demo,dashboard]"
retobs quickstart
```

`retobs quickstart` scans a synthetic corpus, builds stress-test queries, runs a BM25
benchmark, seeds a few production traces, and opens the dashboard at
`http://localhost:4000`. When it finishes you are looking at a real run.

## 2. Understand overall performance (the Overview)

The dashboard opens on the run overview. Read it top-down — it is designed so the most
important conclusion is first:

- **Headline quality** (recall@k, nDCG@k) and **latency** for each pipeline.
- **Biggest failures** — the queries dragging your score down.
- **Recommendations** — the Advisor's ranked suggestions (see
  [advisor.md](advisor.md)).
- **Benchmark health** — dataset fingerprint, seed, and any validation warnings.

You should not need to open another page to know whether the run is good.

## 3. Find a failing query

From the overview, open the **Query Explorer**. Filter to failures (toggle *Mismatches
only*, or search). Pick a query with low recall — one where a relevant document did not make
the final top-k.

## 4. Locate the responsible stage (candidate flow)

This is the core debugging move. On a failing query row, click **⇄ flow** and enter the
`doc_id` of the relevant document that was missed. The **candidate flow** panel shows that
document's journey through every pipeline:

- where it was **introduced** (which retrieval arm found it),
- how its rank **changed** at each operator,
- and, if it disappeared, exactly **where it was dropped and why** (e.g. `reranked_out`,
  `filtered`, `truncated`).

If the drop reason was not explicitly recorded, the panel says so and marks the reason as
*inferred* — retobs never fabricates an explanation.

The panel also exposes **replay verification**: how a counterfactual "what if this operator
weren't here" would be constructed, so you can judge the attribution rather than trust it
blindly.

## 5. Confirm the cause (attribution)

Open **Per-stage attribution**. Each operator's contribution is shown with a confidence
interval, a significance verdict (BH-corrected), and honest *low-power* / *not replayable*
states. If the reranker that dropped your document shows a significant negative contribution,
you have found the culprit — with evidence.

## 6. Improve and validate

Apply the Advisor's recommendation (for example, swap or tune the reranker, increase
first-stage `k`, or add a dense arm — see [hybrid-retrieval.md](hybrid-retrieval.md)). Then
run again:

```bash
retobs run --config your-config.yaml
```

Open **Run Comparison**, select the two runs, and read the diff. The **comparability
banner** at the top warns you if the two runs are not actually comparable (different dataset
content, seed, code version). If they are comparable, confirm the failing query recovered and
that overall quality improved without a latency regression you can't afford.

That is the full loop. Everything else in retobs is a deeper version of one of these steps.

---

## Where to go next

- [hybrid-retrieval.md](hybrid-retrieval.md) — combine lexical + dense retrieval
- [multi-stage-reranking.md](multi-stage-reranking.md) — reranking without dropping recall
- [counterfactual-replay.md](counterfactual-replay.md) — how attribution actually works
- [advisor.md](advisor.md) — turning diagnostics into a prioritized plan
- [conditional-pipelines.md](conditional-pipelines.md) — gated / routed pipelines
