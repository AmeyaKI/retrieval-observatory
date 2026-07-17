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
retobs demo
```

`retobs demo` scans a synthetic corpus, builds stress-test queries, runs a BM25
benchmark, seeds a few production traces, and opens the dashboard at
`http://localhost:4000`. When it finishes you are looking at a real run.

The newest run loads automatically on the Runs page — you should not need to
refresh and click before Overview appears.

### Longer multi-stage demo (<10 minutes)

For candidate-flow diagnosis you need a pipeline that actually filters documents
(single-stage BM25 alone is a weak showcase). Prefer the SciFact hybrid smoke:

```bash
pip install -e ".[dense,dashboard]"
# SciFact + max_queries:50 — typically a few minutes; first dense index is the slow part
retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_scifact.yaml
retobs serve --db .retobs/hybrid_scifact_demo.db
```

Alternatively (no BEIR download): `retobs demo --full`, then
`retobs serve --db .retobs/demo/results.db` (adds a BM25→rerank ablation on the synthetic corpus).

**Public CLI reminder:** use `retobs evaluate --config …` (not `retobs run`, which is removed).
Other common commands: `retobs demo`, `retobs serve --db …`, `retobs compare`,
`retobs inspect-query`, `retobs production demo`.

**60-second click path after serve:** Runs (auto-selected) → Architecture (DAG boxes readable) →
Queries → open a low-recall query → click an FN row → **Play** on the stage flowchart →
Production tab (services/summary load as JSON, not HTML errors).

## 2. Understand overall performance (the Overview)

The dashboard opens on the run overview. Read it top-down — it is designed so the most
important conclusion is first:

- **Headline quality** (recall@k, nDCG@k) and **latency** for each pipeline.
- **Biggest failures** — the queries dragging your score down.
- **Recommended next steps** — evidence-scoped findings (see
  [advisor.md](advisor.md)).
- **Evidence health** — dataset fingerprint, seed, sample size, and validation warnings.

You should not need to open another page to know whether the run is good.

## 3. Find a failing query

From the overview, open **Queries**. The list leads with **query text** (not opaque IDs).
Filter to failures (toggle *Mismatches only*, or search). Pick a query with a weak
outcome — one where a relevant chunk did not make the final top-k.

## 4. Locate the responsible stage (candidate flow)

This is the core debugging move. Open a failing query. The page leads with diagnosis:

1. A **stage flowchart** at the top animates how a selected chunk moves through each
   operator (introduced → passed → dropped/survived). Use **Play** / Prev / Next.
2. Below it, an **expected vs retrieved** table labels every seen candidate as
   **TP / FP / FN / TN** (seen-candidate universe — not corpus-wide negatives). Rows show
   chunk preview, pipeline, where it was lost, and why. Click a row to drive the flowchart.

If the drop reason was not explicitly recorded, the UI marks it as *inferred* — retobs never
fabricates an explanation. Replay assumptions for the dropping operator remain inspectable
under the table.

Deep-link a specific document with
`#/runs/<run>/queries/<query>/candidates/<doc_id>`.

## 5. Confirm the cause (attribution)

Open **Per-stage attribution**. Each operator's contribution is shown with a confidence
interval, a significance verdict (BH-corrected), and honest *low-power* / *not replayable*
states. If the reranker that dropped your document shows a significant negative contribution,
you have found the culprit — with evidence.

## 6. Improve and validate

Apply the evidence-backed recommendation (for example, swap or tune the reranker, increase
first-stage `k`, or add a dense arm — see [hybrid-retrieval.md](hybrid-retrieval.md)). Then
run again:

```bash
retobs evaluate --config your-config.yaml
```

Open **Compare**, select the baseline and candidate runs, and read the diff. The **validity
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
