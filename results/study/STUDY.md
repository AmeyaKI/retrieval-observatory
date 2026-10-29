# Where multi-stage retrieval pipelines lose gold documents they had already found

> **Status: provisional, 13 of 14 grid cells.** Missing: `hotpotqa__hotpot_routed`, so Q3 is pending. The pre-registration ties the headline to the complete grid, so the Q1 figure below is provisional; the pooled figures cover nfcorpus, scifact and fiqa only.
>
> **Version.** Every cell was produced by retobs development builds `3011898` (2026-09-17) and `28bab6c` (2026-09-20), between the 0.6.0 and 0.7.0 releases (see §2 for which cell used which). Every figure below is the renderer's output from the committed cells under [`cells/`](cells/) at commit `29c67b8`, unchanged; only this note and §9 were edited by hand.
>
> **Not rerunnable on current releases.** The 0.7.0 rebuild removed the loss-attribution and counterfactual replay modules the study scripts import, so §5 in particular describes a feature the current package no longer has. Rerunning the study on the current version is recorded as future work in [`FUTURE_WORK.md`](../../FUTURE_WORK.md#research-study).

## Finding

**Provisional:** Self-inflicted loss was rare: 4.8% [4.1%, 5.7%] of recall@10 misses in hybrid pipelines across 1,271 queries on 3 datasets had been surfaced upstream and displaced; the rest were never surfaced.

Branch: **null** (PREREGISTRATION.md §2). Decision inputs: pooled fraction 4.8% [4.1%, 5.7%], interval width 1.6% (rule: at most 20%), lineage completeness 100.0% (rule: at least 95%), threshold 10%.

## 1. Questions and definitions

The study asks where recall is lost inside multi-stage retrieval pipelines, using the lineage retobs records at every operator. The three primary questions, their statistics, and the expected directions were committed in [`PREREGISTRATION.md`](PREREGISTRATION.md) before any cell ran; everything else here is labelled exploratory.

- **Q1.** What fraction of recall@10 misses are *self-inflicted*: the gold document reached the top 10 at some operator's output and a later operator pushed it out?
- **Q2.** Does adding a cross-encoder rerank stage change that fraction, and what does the reranker contribute to nDCG@10?
- **Q3.** In the routed HotpotQA pipeline, which operator class carries the largest share of the loss, and how much of it is recovered later?

For each (query, gold document) pair: **delivered** if it is in the final top 10; **destroyed** if it was inside the top 10 at some operator's output and is not delivered — the *destroying operator* is the last one that moved it from inside the window at its input to outside at its output; **surfaced, never in window** if some operator returned it but never in its top 10; **never surfaced** if no operator returned it (the retrieval ceiling). The **self-inflicted fraction** is destroyed ÷ all misses. **Loss share** of an operator class is its share of destroyed events. Full definitions: PREREGISTRATION.md §3.

## 2. Grid and provenance

| Dataset | Pipeline | Run | Queries | Gold pairs | Lineage complete | Build |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| nfcorpus | 1 · BM25 | `b85b9c3d` | 323 | 12,334 | 100.0% | `3011898` |
| nfcorpus | 2 · dense | `9ebd41f8` | 323 | 12,334 | 100.0% | `3011898` |
| nfcorpus | 3 · RRF hybrid | `ed5c79d3` | 323 | 12,334 | 100.0% | `3011898` |
| nfcorpus | 4 · hybrid + rerank | `0f887214` | 323 | 12,334 | 100.0% | `28bab6c` |
| scifact | 1 · BM25 | `e1f7c62b` | 300 | 339 | 100.0% | `3011898` |
| scifact | 2 · dense | `887a82fc` | 300 | 339 | 100.0% | `3011898` |
| scifact | 3 · RRF hybrid | `d0c401b7` | 300 | 339 | 100.0% | `3011898` |
| scifact | 4 · hybrid + rerank | `926e5bf9` | 300 | 339 | 100.0% | `28bab6c` |
| fiqa | 1 · BM25 | `fdb60340` | 648 | 1,706 | 100.0% | `3011898` |
| fiqa | 2 · dense | `b5a967d4` | 648 | 1,706 | 100.0% | `28bab6c` |
| fiqa | 3 · RRF hybrid | `1f9ac963` | 648 | 1,706 | 100.0% | `28bab6c` |
| fiqa | 4 · hybrid + rerank | `0513c221` | 648 | 1,706 | 100.0% | `28bab6c` |
| fiqa | R · BM25 + rerank | `94b95824` | 648 | 1,706 | 100.0% | `28bab6c` |
| hotpotqa | 5 · routed (HotpotQA) | not run | — | — | — | — |

BEIR test splits in full (nfcorpus, scifact, fiqa); no subsampling was needed. Dense encoder `sentence-transformers/all-MiniLM-L6-v2`; cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2`; both on CPU. Every Run was produced by the same executor as `retobs evaluate` into `results/study/results.db`; the per-cell JSON beside this file holds every statistic and every (query, gold) event. Intervals: 2,000-resample percentile cluster bootstrap over queries, seed 17. No latency figure is reported anywhere in this study.

## 3. Where the misses come from

Share of recall@10 misses by cause, per pipeline and dataset. The BM25 and dense pipelines have one operator, so nothing can be self-inflicted; they are the control rows and show the retrieval ceiling.

| Pipeline | Dataset | Misses | Self-inflicted | Surfaced, never top 10 | Never surfaced |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 · BM25 | nfcorpus | 11,723 | 0.0% [0.0%, 0.0%] | 8.5% [7.2%, 10.0%] | 91.5% [90.0%, 92.8%] |
| 1 · BM25 | scifact | 117 | 0.0% [0.0%, 0.0%] | 38.5% [29.5%, 47.5%] | 61.5% [52.5%, 70.5%] |
| 1 · BM25 | fiqa | 1,407 | 0.0% [0.0%, 0.0%] | 19.6% [17.5%, 21.9%] | 80.4% [78.1%, 82.5%] |
| 2 · dense | nfcorpus | 11,562 | 0.0% [0.0%, 0.0%] | 15.4% [13.9%, 17.2%] | 84.6% [82.8%, 86.1%] |
| 2 · dense | scifact | 72 | 0.0% [0.0%, 0.0%] | 65.3% [53.3%, 75.9%] | 34.7% [24.1%, 46.7%] |
| 2 · dense | fiqa | 1,029 | 0.0% [0.0%, 0.0%] | 46.2% [42.9%, 49.4%] | 53.8% [50.6%, 57.1%] |
| 3 · RRF hybrid | nfcorpus | 11,574 | 2.7% [2.3%, 3.2%] | 16.5% [15.0%, 18.2%] | 80.9% [78.8%, 82.6%] |
| 3 · RRF hybrid | scifact | 88 | 40.9% [30.7%, 51.2%] | 43.2% [32.1%, 53.7%] | 15.9% [8.4%, 24.1%] |
| 3 · RRF hybrid | fiqa | 1,144 | 21.0% [18.2%, 23.7%] | 35.8% [32.9%, 38.5%] | 43.3% [40.2%, 46.6%] |
| 4 · hybrid + rerank | nfcorpus | 11,551 | 3.6% [3.1%, 4.2%] | 15.4% [14.0%, 17.1%] | 81.0% [78.9%, 82.8%] |
| 4 · hybrid + rerank | scifact | 67 | 35.8% [23.7%, 47.8%] | 43.3% [30.8%, 55.4%] | 20.9% [11.4%, 31.3%] |
| 4 · hybrid + rerank | fiqa | 1,029 | 19.0% [16.7%, 21.5%] | 32.8% [29.9%, 35.8%] | 48.1% [44.8%, 51.5%] |
| **3 + 4 pooled** | nfcorpus, scifact, fiqa | 25,453 | **4.8% [4.1%, 5.7%]** | 17.7% [16.2%, 19.5%] | 77.6% [75.1%, 79.6%] |

The pooled row weights every (query, gold) pair equally, as pre-registered, so it follows the datasets with the most graded golds: share of pooled misses — nfcorpus 90.9%; scifact 0.6%; fiqa 8.5%. Read the per-dataset rows beside it.

**Loss share by operator class** (destroyed events only; classes with no event in any cell are omitted — filter/dedup, routing/merge, expand, and other have no operator in pipelines 3 and 4).

| Pipeline | Dataset | Destroyed | Fusion | Rerank |
| --- | --- | ---: | ---: | ---: |
| 3 · RRF hybrid | nfcorpus | 308 | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] |
| 3 · RRF hybrid | scifact | 36 | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] |
| 3 · RRF hybrid | fiqa | 240 | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] |
| 4 · hybrid + rerank | nfcorpus | 413 | 48.7% [43.4%, 53.3%] | 51.3% [46.7%, 56.6%] |
| 4 · hybrid + rerank | scifact | 24 | 66.7% [47.6%, 85.0%] | 33.3% [15.0%, 52.4%] |
| 4 · hybrid + rerank | fiqa | 196 | 54.6% [47.5%, 61.7%] | 45.4% [38.3%, 52.5%] |
| **3 + 4 pooled** | nfcorpus, scifact, fiqa | 1,217 | 74.6% [71.7%, 77.3%] | 25.4% [22.7%, 28.3%] |

**Fixed K = 50 variant** (PREREGISTRATION.md §3.1): the same misses, counting a gold as surfaced only where it appeared at rank ≤ 50. The self-inflicted fraction does not change by construction, so in pipelines 3 and 4 the two columns sum to 100% minus the self-inflicted share in the first table.

| Pipeline | Dataset | Surfaced ≤ 50, never top 10 | Not surfaced within 50 |
| --- | --- | ---: | ---: |
| 1 · BM25 | nfcorpus | 5.9% [5.1%, 7.0%] | 94.1% [93.0%, 94.9%] |
| 1 · BM25 | scifact | 30.8% [22.5%, 39.6%] | 69.2% [60.4%, 77.5%] |
| 1 · BM25 | fiqa | 14.1% [12.3%, 16.1%] | 85.9% [83.9%, 87.7%] |
| 2 · dense | nfcorpus | 9.5% [8.5%, 10.8%] | 90.5% [89.2%, 91.5%] |
| 2 · dense | scifact | 51.4% [39.7%, 62.5%] | 48.6% [37.5%, 60.3%] |
| 2 · dense | fiqa | 31.2% [28.2%, 34.4%] | 68.8% [65.6%, 71.8%] |
| 3 · RRF hybrid | nfcorpus | 10.6% [9.6%, 11.8%] | 86.8% [85.1%, 88.1%] |
| 3 · RRF hybrid | scifact | 34.1% [24.0%, 44.2%] | 25.0% [16.0%, 34.4%] |
| 3 · RRF hybrid | fiqa | 24.1% [21.7%, 26.5%] | 54.9% [51.6%, 58.1%] |
| 4 · hybrid + rerank | nfcorpus | 10.5% [9.5%, 11.8%] | 85.9% [84.1%, 87.3%] |
| 4 · hybrid + rerank | scifact | 31.3% [19.6%, 43.1%] | 32.8% [21.2%, 45.3%] |
| 4 · hybrid + rerank | fiqa | 20.4% [17.9%, 22.8%] | 60.5% [57.2%, 63.7%] |

## 4. Recovery

A recovery is a gold pushed out of the top 10 by one operator and moved back in by a later one. In pipelines 3 and 4 only the reranker can follow a displacing operator, and it sees only the fused list, so recoveries are possible only there.

| Pipeline | Dataset | Displaced pairs | Recovered | Re-displaced after recovery | First ≠ last displacer | Set-level re-finds (exploratory) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 3 · RRF hybrid | nfcorpus | 308 | 0.0% [0.0%, 0.0%] | undefined (0 of 0) | 0 | 0 |
| 3 · RRF hybrid | scifact | 36 | 0.0% [0.0%, 0.0%] | undefined (0 of 0) | 0 | 0 |
| 3 · RRF hybrid | fiqa | 240 | 0.0% [0.0%, 0.0%] | undefined (0 of 0) | 0 | 0 |
| 4 · hybrid + rerank | nfcorpus | 520 | 20.6% [16.6%, 24.9%] | 0.0% [0.0%, 0.0%] | 0 | 0 |
| 4 · hybrid + rerank | scifact | 44 | 45.5% [30.3%, 61.1%] | 0.0% [0.0%, 0.0%] | 0 | 0 |
| 4 · hybrid + rerank | fiqa | 329 | 40.4% [34.9%, 45.6%] | 0.0% [0.0%, 0.0%] | 0 | 0 |

## 5. Marginal contributions by replay tier

Counterfactual replay removes one operator and replays the recorded lineage (strict rule: `indeterminate` whenever a later operator would have to rank documents it never saw). FUSE replays are EXACT (RRF is recomputed); RERANK replays are OBSERVED_ABLATION (the reranker's input order is passed through). Tiers are never averaged together. Sign-flip test, Benjamini-Hochberg q-values per pipeline.

| Pipeline | Dataset | Operator | Tier | Replay strategy | Δ nDCG@10 [95% CI] | Δ recall@10 | q | Queries |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 3 · RRF hybrid | nfcorpus | `fuse` | EXACT | `remove_outputs` | +0.048 [+0.035, +0.061] | +0.027 | 0.0005 | 323 |
| 3 · RRF hybrid | scifact | `fuse` | EXACT | `remove_outputs` | +0.084 [+0.058, +0.111] | +0.082 | 0.0005 | 300 |
| 3 · RRF hybrid | fiqa | `fuse` | EXACT | `remove_outputs` | +0.141 [+0.125, +0.158] | +0.175 | 0.0005 | 648 |
| 4 · hybrid + rerank | nfcorpus | `fuse` | EXACT | `remove_outputs` | +0.000 [+0.000, +0.000] | +0.000 | 1.0000 | 323 |
| 4 · hybrid + rerank | nfcorpus | `rerank` | OBSERVED_ABLATION | `rerank_passthrough_inputs` | +0.026 [+0.009, +0.044] | +0.012 | 0.0110 | 323 |
| 4 · hybrid + rerank | scifact | `fuse` | EXACT | `remove_outputs` | +0.000 [+0.000, +0.000] | +0.000 | 1.0000 | 300 |
| 4 · hybrid + rerank | scifact | `rerank` | OBSERVED_ABLATION | `rerank_passthrough_inputs` | +0.042 [+0.010, +0.074] | +0.059 | 0.0320 | 300 |
| 4 · hybrid + rerank | fiqa | `fuse` | EXACT | `remove_outputs` | +0.000 [+0.000, +0.000] | +0.000 | 1.0000 | 648 |
| 4 · hybrid + rerank | fiqa | `rerank` | OBSERVED_ABLATION | `rerank_passthrough_inputs` | +0.067 [+0.048, +0.086] | +0.064 | 0.0010 | 648 |
| R · BM25 + rerank | fiqa | `rerank` | OBSERVED_ABLATION | `rerank_passthrough_inputs` | +0.111 [+0.093, +0.130] | +0.107 | 0.0005 | 648 |

A positive Δ means the pipeline scores higher *with* the operator than without it. What each replay strategy does, as recorded with the result:

- `remove_outputs`: Removed this operator's contributed documents from every downstream stage; downstream re-ranking was not recomputed.
- `rerank_passthrough_inputs`: Replaced this reranker's output with its input ordering; original downstream scores were reused, not recomputed by a real model call.

A fusion step that is not the last operator is replayed by `remove_outputs`, which removes only documents the fusion introduced itself. RRF introduces none, so its Δ there is zero by construction and says nothing about how much the fused order helped; the fused order's effect is measured where fusion is the final operator (pipeline 3).

**Final-stage quality** (context for the tables above; nDCG@10 with linear gain, 95% CI).

| Dataset | 1 · BM25 | 2 · dense | 3 · RRF hybrid | 4 · hybrid + rerank |
| --- | ---: | ---: | ---: | ---: |
| nfcorpus | 0.267 [0.235, 0.299] | 0.309 [0.276, 0.343] | 0.315 [0.281, 0.348] | 0.340 [0.306, 0.375] |
| scifact | 0.547 [0.497, 0.598] | 0.640 [0.594, 0.684] | 0.631 [0.580, 0.681] | 0.673 [0.630, 0.717] |
| fiqa | 0.163 [0.142, 0.184] | 0.369 [0.341, 0.396] | 0.304 [0.279, 0.329] | 0.371 [0.346, 0.398] |

## 6. Findings

Primaries first, each beside its pre-registered expectation. A result against the expectation is reported in the same place and the same form as one that confirms it.

**Q1.** Pooled over pipelines 3 and 4 on nfcorpus, scifact, fiqa, 4.8% [4.1%, 5.7%] of recall@10 misses were self-inflicted (per dataset: nfcorpus 3.1% [2.7%, 3.7%]; scifact 38.7% [29.0%, 48.9%]; fiqa 20.1% [17.7%, 22.5%]). *Expected: at least 10%.* The result is **against** the expectation. Depends on the 2026-09-20 amendment through pipeline 4.

**Q2.** Adding the cross-encoder changed the self-inflicted fraction by +0.44 pp [+0.04, +0.81] pooled (nfcorpus +0.91 pp [+0.59, +1.28]; scifact -5.09 pp [-14.42, +4.00]; fiqa -1.93 pp [-4.20, +0.22]). The reranker's marginal contribution to nDCG@10 (OBSERVED_ABLATION): nfcorpus +0.026 [+0.009, +0.044]; scifact +0.042 [+0.010, +0.074]; fiqa +0.067 [+0.048, +0.086]. *Expected: a positive marginal contribution and a higher self-inflicted fraction.* In words: pooled, the self-inflicted fraction rose, as expected; it rose on nfcorpus; no change was detected on scifact, fiqa; the reranker raised nDCG@10 on nfcorpus, scifact, fiqa, as expected. A difference counts as detected only when its interval excludes 0 (PREREGISTRATION.md §6). Depends on the 2026-09-20 amendment.

**Q3.** Pending: the HotpotQA routed cell has not run.

**Exploratory** (no pre-registered expectation; not headline material):

- nfcorpus: final nDCG@10 0.315 with RRF alone and 0.340 after the cross-encoder.
- scifact: final nDCG@10 0.631 with RRF alone and 0.673 after the cross-encoder.
- fiqa: final nDCG@10 0.304 with RRF alone and 0.371 after the cross-encoder.
- nfcorpus: the dense lane alone never surfaces 84.6% [82.8%, 86.1%] of its misses in the top 100.
- scifact: the dense lane alone never surfaces 34.7% [24.1%, 46.7%] of its misses in the top 100.
- fiqa: the dense lane alone never surfaces 53.8% [50.6%, 57.1%] of its misses in the top 100.

## 7. Reconciliation with the prior published claim

An earlier published summary of this project reported, for fiqa on build 0.1.0, nDCG@10 of 0.159 for BM25, 0.369 for dense, and 0.260 for BM25 followed by a cross-encoder (`results/BENCHMARK_ANALYSIS.md`), summarised as "+132% nDCG@10 over BM25" together with a latency ratio. A ratio *reproduces* when the prior value lies inside the current build's 95% paired bootstrap interval for the same ratio (PREREGISTRATION.md §8). FiQA's relevance labels are binary, so the change from exponential to linear nDCG gain since that build does not affect these numbers.

| nDCG@10 ratio on fiqa | Prior | Current build [95% CI] | Status | Note |
| --- | ---: | ---: | --- | --- |
| dense ÷ BM25 | 2.32 | 2.26 [2.00, 2.57] | REPRODUCED | 648 paired queries |
| BM25 + rerank ÷ BM25 | 1.64 | 1.68 [1.54, 1.86] | REPRODUCED | 648 paired queries |
| BM25 + rerank ÷ dense | 0.70 | 0.74 [0.68, 0.80] | REPRODUCED | 648 paired queries |
| hybrid + rerank ÷ dense | — | 1.01 [0.95, 1.06] | — | different configuration from the prior rerank arm; shown, not reconciled |

The latency half of the prior claim is **not measured** in this study (no latency figure is recorded in any study artifact) and cannot be reconciled here; it stands withdrawn unless re-measured separately with the machine named.

## 8. Limitations

- BEIR relevance labels are incomplete: an unlabelled document in the top 10 counts as a miss for the gold it displaced even if it is also relevant. Absolute fractions depend on how densely each dataset is labelled.
- Small encoders on CPU (MiniLM-L6 bi-encoder and cross-encoder). Larger models would move every ceiling and loss figure; the method, not the magnitudes, is what transfers.
- Single-seed grid. The intervals capture query sampling, not model or index variance.
- Pipelines 3 and 4 have one or two non-source operators, so their loss shares are close to tautological (fusion is the only possible destroyer in pipeline 3). The class comparison with real content is Q3.
- Replay tiers differ in strength: EXACT (fusion) replays recompute the operator's function; OBSERVED_ABLATION (rerank) replays pass the input order through and reuse recorded downstream scores.
- The pooled Q1 figure weights (query, gold) pairs equally and is therefore dominated by the dataset with the most graded golds per query; the per-dataset rows are the more informative view.
- HotpotQA uses the flagship-demo subset (a 12,654-paragraph corpus built from the 1,300 sampled questions' bundled paragraphs), not the full corpus, so its retrieval ceiling is far easier than full-corpus HotpotQA.

## 9. Reproduce

The study scripts run only on the build that produced them; on current releases they fail at import. The committed cells are the source of truth; `results/study/results.db` stays local.

```bash
git checkout 29c67b8
pip install -e ".[beir,demo,dense]"       # that tree: BEIR loader, BM25, sentence-transformers
python scripts/study_loss_attribution.py  # runs missing cells; finished cells are skipped
python scripts/render_study.py            # re-renders from results/study/cells/: every figure matches this file
```

Pre-registration and amendments: [`PREREGISTRATION.md`](PREREGISTRATION.md). The 2026-09-17 replay amendment affects only pipeline 5's marginal contributions. The 2026-09-20 reranker-text amendment affects every pipeline 4 and R figure, and through them the pooled Q1 figure, Q2, and the rerank rows of §7.
