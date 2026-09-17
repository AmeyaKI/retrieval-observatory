# Pre-registration: where multi-stage retrieval pipelines lose gold documents they had already found

| | |
| --- | --- |
| Status | Committed before any grid cell has run. See "Amendments" at the end. |
| Build | retobs `main` at the commit that adds this file (0.6.0 plus the 2026-09-15 review-cycle fixes; `CHANGELOG.md` [Unreleased]) |
| Governing brief | `STUDY_BRIEF.md` Phase B (local, untracked) |
| Analysis code | `retrieval_observatory/analysis/loss_attribution.py` (to be written after this file is committed) |
| Driver | `scripts/study_loss_attribution.py`; write-up `scripts/render_study.py` → `results/study/STUDY.md` |

**Amendment policy.** Once the first grid cell has run, nothing above the "Amendments" section is
edited. Any change is appended there with a date, the reason, and what it would have changed had it
been in force from the start. A finding that depends on an amendment is labelled as such in
`STUDY.md`.

## 1. Primary questions

Everything not listed here is exploratory and is labelled "exploratory" wherever it appears in
`STUDY.md`. Null and reversed results on the primaries are reported with the same prominence as
confirmations, in the same table and the same sentence position.

### Q1. What fraction of recall misses at k=10 are self-inflicted?

- **Statistic.** Self-inflicted loss fraction (definition §3.8): destroyed-recall events ÷ (destroyed
  + never-surfaced + surfaced-never-in-window), computed over every (query, gold document) pair.
- **Comparison.** Pooled over pipelines 3 and 4 (the hybrid pipelines) on nfcorpus, scifact, and
  fiqa, with each (query, gold) pair weighted equally. Also reported per pipeline × dataset.
  Pipelines 1 and 2 have exactly one operator, so their self-inflicted fraction is 0 by construction;
  they are reported as the control row and supply the never-surfaced ceiling.
- **Interval.** 95% cluster bootstrap over queries (§6).
- **Expected direction.** The pooled fraction is at least 10%: a material minority of hybrid-pipeline
  misses are documents an upstream stage had already placed in the top 10.

### Q2. Does adding a cross-encoder rerank stage change the self-inflicted loss rate?

- **Statistic.** Difference in self-inflicted loss fraction, pipeline 4 minus pipeline 3, on the same
  queries, per dataset and pooled over the three BEIR datasets. Second statistic: the reranker's
  marginal contribution to nDCG@10 and recall@10 from the existing counterfactual replay
  (`tracing/attribution.py::operator_marginal_contribution`), reported with its replay tier
  (OBSERVED_ABLATION under `pipeline/dag.py::DEFAULT_REPLAY_POLICY`) and its indeterminate count.
- **Comparison.** Paired: the two pipelines share the same fused candidate list up to the reranker,
  so each query's events are compared under both.
- **Interval.** 95% paired cluster bootstrap over queries for the difference (§6); the marginal
  contribution uses the repo's sign-flip test with Benjamini-Hochberg correction.
- **Expected direction.** The reranker raises nDCG@10 and recall@10 (positive marginal contribution)
  *and* raises the self-inflicted fraction of the misses that remain: it can recover documents fusion
  pushed out of the window, but every document it demotes from the fused top 10 is a new
  self-inflicted event, and the misses it fixes leave the denominator.

### Q3. In the routed HotpotQA pipeline, which operator class carries the largest loss share, and how much is recovered?

- **Statistic.** Loss share by operator class (§3.9) in pipeline 5 on the HotpotQA subset, with a
  per-operator breakdown of all eleven operators alongside; recovery rate (§3.7): displaced golds
  later moved back into the window ÷ displaced golds; re-displacement rate among recovered golds.
- **Comparison.** Classes against each other within pipeline 5; the class with the largest share is
  named, and whether its interval overlaps the runner-up's is stated.
- **Interval.** 95% cluster bootstrap over queries (§6).
- **Expected direction.** Fusion carries the largest share: the two RRF merges (`hybrid_fusion`,
  `route_merge`) touch every served query and RRF displaces a document one lane ranked highly when
  the other lane missed it. Rerank second. The expand class recovers more golds than it displaces.
  The routing/merge class (the two GATE operators) has a share of 0 by construction, because a gate
  passes its input through unchanged (§4). Fewer than half of displaced golds are recovered.

## 2. Headline-sentence decision rule

`STUDY.md` opens with one sentence rendered by `scripts/render_study.py` from the Q1 pooled
statistic *f* with 95% interval [*lo*, *hi*]. The branch is chosen by these rules, in this order,
and not by eye:

1. **Indeterminate** if lineage completeness is below 95%: completeness is the share of (query,
   gold) pairs in pipelines 3 and 4 whose query trace has status OK and whose lineage is not marked
   partial (`NormalizationReport`/`lineage_incomplete`). Also indeterminate if *hi* − *lo* > 0.20.
2. **Positive** if *lo* ≥ 0.10. Rendered as: "Across N queries on 3 datasets, X% [lo, hi] of
   recall@10 misses in hybrid pipelines were self-inflicted: the gold document was surfaced upstream
   and displaced by a later stage, most often by {class}." `{class}` is the class with the largest
   pooled loss share over pipelines 3 and 4; if its interval overlaps the runner-up's, the sentence
   reads "most often by {class}, not separable from {class2}".
3. **Null** if *hi* < 0.10. Rendered as: "Self-inflicted loss was rare: X% [lo, hi] of recall@10
   misses in hybrid pipelines across N queries on 3 datasets had been surfaced upstream and
   displaced; the rest were never surfaced."
4. **Indeterminate** otherwise (the interval straddles 10%). Rendered as: "Self-inflicted loss was
   X% [lo, hi] of recall@10 misses in hybrid pipelines; the interval does not settle whether it is
   material," followed by the completeness and width figures.

The 10% threshold is the level at which one miss in ten is a document the pipeline had already found;
below that, the retrieval ceiling dominates and the headline should say so. The same sentence goes
in `README.md` under the Study link.

## 3. Definitions

All definitions are evaluated on the lineage the runner recorded: each `OperatorSpan`'s
`input_groups` and `outputs`, each `Candidate`'s `rank`, `input_rank`, and `output_rank`. Nothing is
re-derived from scores. Only spans with status FIRED participate; SKIPPED_BY_GATE spans have no
candidates. **k = 10** throughout.

1. **Surfaced.** Gold document *g* appears in the `outputs` of at least one FIRED operator in query
   *q*'s trace, at any rank (candidate width as recorded). A fixed **K = 50** variant counts *g* as
   surfaced only where it appears at output rank ≤ 50; both are reported.
2. **Never surfaced.** *g* appears in no FIRED operator's outputs. A retrieval-ceiling miss. Counted
   and reported; never attributed to an operator.
3. **Delivered.** *g* appears at rank ≤ 10 in the outputs of the trace's final operator
   (`final_op_ids`). For a trace with several final operators, any of them.
4. **Delivery window.** Positions 1 to 10 of a ranked candidate list. For an operator whose outputs
   carry no ranks (a filter or dedup that returns a set), the window is set membership.
   *In the window at an operator's input* means rank ≤ 10 in at least one of its `input_groups`;
   *in the window at its output* means output rank ≤ 10.
5. **Surfaced, never in window.** *g* is surfaced (1) but at no FIRED operator's output is it at
   rank ≤ 10. Reported separately; part of the Q1 denominator; never attributed to an operator.
6. **Destroyed-recall event and destroying operator.** *g* was in the window at some operator's
   output and is not delivered. An operator **displaces** *g* when *g* is in the window at that
   operator's input and outside it at that operator's output (rank > 10, or absent). The
   **destroying operator** is the *last* displacing operator in the trace's topological order; the
   **first** displacing operator is recorded too. The final top-k cut is not an operator and is never
   a destroyer: a document at final rank 14 was displaced by whichever operator moved it past 10.
   Any operator that truncates its own output (fusion `top_k`, rerank `top_k`) is a displacer for
   the documents it cuts from the window, recorded with `drop_reason="truncated"` by the executor.
7. **Recovery.** *g* displaced out of the window by some operator and back inside the window at a
   later operator's output. **Re-displacement**: a recovered *g* displaced again afterwards; counted
   separately. Recovery is window-level. Note for the record: in the current Scenario D trace
   (`results/flagship_demo/reports/scenario-d-lineage.txt`) the second gold is at dense rank 27,
   cut by `hybrid_fusion`, and re-found by `bridge_hop2` at rank 45. That is a candidate-set re-find,
   never a window event, and under these definitions it is a "surfaced, never in window" miss, not
   a recovery. Set-level re-finds are counted as an exploratory statistic and are not recoveries.
8. **Self-inflicted loss fraction** per pipeline per dataset: destroyed-recall events ÷ (destroyed +
   never surfaced + surfaced-never-in-window). Delivered golds are not in the denominator; this is a
   fraction of misses. The headline statistic.
9. **Loss share** of operator class C on dataset D: destroyed-recall events whose destroying
   operator is of class C ÷ all destroyed-recall events on D.
10. **Marginal contribution.** The existing counterfactual replay attribution (nDCG@10 and recall@10
    deltas from `simulate_without_operator`), reported per operator class with its replay tier.
    EXACT and OBSERVED_ABLATION figures are never averaged into one number. An `indeterminate`
    replay (strict rule: a child would have to decide on documents it never observed) or a
    NOT_REPLAYABLE operator is reported as indeterminate with a count, never estimated around.
11. **Unit tests** the implementation must pass before any cell runs, as mandated by the brief:
    gold at rank 6 → rerank moves it to 14 → truncate (destroyer = rerank, first = rerank);
    gold at rank 30 after the first stage → fusion moves it to 4 → filter removes it (destroyer =
    filter; the fusion move is *not* a recovery because nothing had displaced it; a variant where a
    prior operator displaced it first counts a recovery at fusion and the filter as re-displacement);
    gold never above rank 40 (surfaced, never in window); gold absent everywhere (never surfaced);
    the single-operator control (no displacement possible); a multi-parent fuse whose input window
    is met through one parent group only.

## 4. Operator class mapping

Mapped from the recorded `op_type`, never from the operator's name. Decided with the owner on
2026-09-16.

| Class | `op_type` | Operators in the grid |
| --- | --- | --- |
| fusion | FUSE | pipelines 3 and 4: `fuse`; pipeline 5: `hybrid_fusion`, `route_merge`, `final_selection` |
| rerank | RERANK | pipeline 4: `rerank`; pipeline 5: `rerank` |
| filter/dedup | FILTER | none in this grid (the unit tests cover it) |
| routing/merge | GATE | pipeline 5: `type_gate`, `confidence_gate` |
| expand | EXPAND | pipeline 5: `bridge_hop2`, `bridge_siblings`, `comparison_widen` |
| other | TRANSFORM, BOOST, GENERATE | pipeline 5: `fast_lane` (TRANSFORM; a renumbering no-op) |
| (not a class) | SOURCE | every source lane; has no input, so it can never displace |

Two consequences stated up front so they cannot look like findings later: gates pass candidates
through unchanged, so the routing/merge share is 0 unless a gate truncates (none does); and
`route_merge` and `final_selection` are FUSE by `op_type` and are classed as fusion even though they
sit after routing. The per-operator breakdown in Q3 shows each of them separately. Anything whose
`op_type` is not in the table is reported under "other" and named in `STUDY.md`.

## 5. Grid

### Pipelines

All five are declared as DAG graphs (`graphs:` / `PipelineGraphSpec`), never as linear `pipelines:`,
so every span records its `op_type` and input/output ranks. Widths are fixed before running.

| # | Id | Nodes (op_type, params) | Notes |
| --- | --- | --- | --- |
| 1 | `bm25_only` | `bm25` (SOURCE, k=100) | control; one operator, no displacement possible |
| 2 | `dense_only` | `dense` (SOURCE, `sentence-transformers/all-MiniLM-L6-v2`, k=100) | one operator; supplies the dense-vs-BM25 reconciliation |
| 3 | `rrf_hybrid` | `bm25` (k=100), `dense` (k=100) → `fuse` (FUSE, rrf_k=60, top_k=100) | |
| 4 | `hybrid_rerank` | pipeline 3 → `rerank` (RERANK, `cross-encoder/ms-marco-MiniLM-L-6-v2`, top_k=100) | the reranker scores all 100 fused candidates and returns the full re-order so ranks past 10 are recorded; cost is identical to returning 10 |
| R | `bm25_rerank` (fiqa only) | `bm25` (k=100) → `rerank` (RERANK, same cross-encoder, top_k=100) | reconciliation-only cell (§8); excluded from every pooled statistic |
| 5 | `hotpot_routed` | `results/flagship_demo/pipeline.py` with default `PipelineSettings` (lanes 30, fusion top_k 40, hop-2 depth 25, sibling limit 10, widen depth 60, rerank candidates 40, final_k 10); eleven operators plus the final fuse | run through `execute_benchmark` exactly as `run.py` does |

Metrics at the final operator: nDCG@10 (linear gain), recall@10, MRR. No latency figure is recorded
in any study artifact (brief B3).

### Datasets and query counts

| Dataset | Split | Queries | Corpus | Pipelines |
| --- | --- | --- | --- | --- |
| BEIR nfcorpus | test | 323 | 3,633 | 1–4 |
| BEIR scifact | test | 300 | 5,183 | 1–4 |
| BEIR fiqa | test | 648 | 57,638 | 1–4, R |
| HotpotQA flagship subset | validation sample, seed 20260803 | **see below** | 12,654 | 5 |

BEIR data is the cached copy under `~/.cache/retrieval_observatory/beir/`. Full test splits are
used; no subsampling is planned. The brief's subsampling rule (seeded, ≥300 queries per dataset,
manifest committed) applies only if the driver's up-front runtime estimate exceeds ~12 h CPU, and any
use of it is recorded in an amendment.

**HotpotQA subset.** The flagship corpus is the union of every paragraph bundled with 1,300
validation questions (`results/flagship_demo/DATA_PROVENANCE.md`); it is identical whichever query
count is used. `data/` is regenerable from `build_corpus.py` (seed 20260803, n=1300, SHA-256
fingerprints in `dataset_manifest.json`) and is not committed. The query manifest for this study is
the ordered list of HotpotQA ids in `queries.jsonl`, committed as
`results/study/hotpotqa_query_manifest.json` by the driver before the cell runs.
Query count: **all 1,300 sampled questions** (decided with the owner 2026-09-17; the published
flagship-demo runs use the first 400 of the same ordered list, so those 400 are a prefix of this
study's queries).

### Seeds and models

- Bootstrap: 2,000 resamples, seed 17 (passed explicitly to `metrics.significance.bootstrap_ci`;
  its defaults are 1,000 and 42).
- Dense encoder: `sentence-transformers/all-MiniLM-L6-v2`. Cross-encoder:
  `cross-encoder/ms-marco-MiniLM-L-6-v2`. Both CPU. Environment: `KMP_DUPLICATE_LIB_OK=TRUE`
  `OMP_NUM_THREADS=1` (`FUTURE_WORK.md`, demo ergonomics).
- Single-seed grid; no model or index randomness beyond the deterministic encoders.

### Execution

Every number comes from a Run written by `runner/execute.py::execute_benchmark` into
`results/study/results.db` (gitignored, like every `*.db`); per-cell JSON under `results/study/cells/`
is committed. Indexes cache under `.retobs/study/cache/`. The driver is idempotent: a cell whose JSON
exists is skipped. Nothing computes a metric outside the tool.

## 6. Statistics

- **Rates** (self-inflicted fraction, never-surfaced fraction, loss share, recovery rate,
  re-displacement rate): the unit is a (query, gold) pair; the interval is a percentile cluster
  bootstrap that resamples *queries* with replacement (2,000 resamples, seed 17) and recomputes the
  pooled rate on each resample, so correlated golds within a query stay together.
- **Q2 difference**: on each of the same 2,000 query resamples, both pipelines' fractions are
  recomputed and subtracted; the interval is the percentile interval of the differences. A
  difference is reported as detected only if that interval excludes 0.
- **Marginal contributions**: the repo's `operator_marginal_contributions` (sign-flip test,
  `(k+1)/(n+1)` p-values, one BH family per pipeline).
- **Replay tiers**: reported separately; never averaged. Indeterminate and NOT_REPLAYABLE counts
  appear next to every marginal figure.
- Pooling weights each (query, gold) pair equally; per-dataset rows are shown beside every pooled
  figure so a large dataset (fiqa) cannot hide the others.

## 7. Counterfactual replay statement

Replay is strict (`tracing/replay.py`, decided 2026-09-15): removing an operator recomputes RRF for
FUSE children and otherwise keeps each descendant's observed outputs filtered to what still flows
in; whenever a descendant would have to decide on documents it never observed, the replay is
`indeterminate`. Tiers come from the runner (`DEFAULT_REPLAY_POLICY`): FUSE EXACT; RERANK, EXPAND,
GATE, TRANSFORM OBSERVED_ABLATION; SOURCE NOT_REPLAYABLE. This study changes none of that; it
reports the indeterminate counts it produces. Only Q2's second statistic and §3.10 depend on
replay; Q1, Q3, and the headline sentence are computed from recorded ranks alone.

## 8. Resume-claim reconciliation plan (STUDY.md §7)

The existing resume bullet cites "+132% NDCG@10 over BM25 on FiQA at 130× lower latency than
cross-encoder reranking", measured on build 0.1.0 (`results/BENCHMARK_ANALYSIS.md`: BM25 0.159,
dense 0.369, BM25→rerank 0.260, rrf 0.290 on 648 fiqa queries).

- **Dense vs BM25.** Pipelines 2 and 1 on fiqa re-derive the ratio on the current build. Rendered
  side by side with the old 0.369 / 0.159. "Reproduces" means the old ratio lies inside the current
  build's bootstrap interval for the ratio (2,000 query resamples, seed 17).
- **Rerank comparison.** The old rerank arm was BM25 top-100 → cross-encoder, which is not pipeline
  4 (hybrid → cross-encoder). Pipeline 4 vs pipeline 2 is rendered and labelled as a different
  configuration. In addition, one reconciliation-only cell `bm25_rerank` on fiqa (`bm25` k=100 →
  `rerank` top_k=100, the old configuration as a graph; decided with the owner 2026-09-17)
  re-derives the old rerank-vs-dense and rerank-vs-BM25 nDCG@10 ratios directly. It is not a
  primary, feeds no pooled statistic, and appears only in STUDY.md §7 and the HANDOFF claim table.
- **Latency.** NOT MEASURED. Out of scope for this study (brief B3); `STUDY.md` says so explicitly
  and `HANDOFF.md` flags the latency half of the bullet for removal unless the owner re-measures it
  separately with the machine named.

## 9. Exploratory analyses (labelled as such wherever they appear)

Everything below is reported without a pre-registered expectation and cannot become a headline.

- Self-inflicted fraction under the fixed K=50 surfaced variant.
- Never-surfaced fraction by pipeline × dataset (the retrieval ceiling).
- Per-operator breakdown in pipelines 3 and 4 (trivially one operator per class) and pipeline 5.
- Set-level re-finds (§3.7 note) in pipeline 5.
- Loss share and recovery split by HotpotQA question type (bridge / comparison) and by the
  confidence-gate route (agree / disagree), on served queries only.
- Marginal contributions of every operator, not just the reranker.
- Any statistic added after the first cell runs (recorded as an amendment first).

## 10. Out of scope

No latency claims, no new operators or subsystems, no change to replay or attribution semantics
(bug fixes get their own commits with tests and are listed in the amendments), no GPU encoders, no
LLM-as-judge, no additional datasets. The resume framing is chosen after the data, never before.

## Amendments

None.
