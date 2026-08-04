# retobs flagship demo — a real multi-stage RAG pipeline on HotpotQA

An eleven-operator retrieval pipeline evaluated on 400 human-annotated HotpotQA questions,
put through four release decisions. Every number on this page came out of a run recorded in
`.retobs/demo.db`; nothing is illustrative.

**No API keys. No accounts. No rate limits.** One command, about four minutes.

```bash
./run_demo.sh          # 400 questions per run (~4 min, ~1.3 GB)
./run_demo.sh 100      # quick pass
```

---

## What this demonstrates

| | The question an engineer is asking | Verdict |
|---|---|---|
| **A** | "I improved something. Can I ship it?" | `PASS` |
| **B** | "Something got worse. Where?" | `PASS` — and that is the interesting part |
| **C** | "Can I trust this comparison at all?" | `BLOCK` |
| **C2** | "What does the check in C actually prevent?" | `BLOCK` |
| **D** | "*Why* did this query fail?" | a named operator and a named document |

## The pipeline

Two search lanes, two routing decisions, a two-hop path for questions that need one.

```
        bm25_lane      dense_lane          keyword + vector, top 30 each
             └──────┬──────┘
             hybrid_fusion                 reciprocal rank fusion, top 40
                    │
              type_gate                    GATE — HotpotQA's bridge/comparison label
             ┌──────┴──────┐
      bridge_hop2      comparison_widen    re-search using the bridge entity | wider single pass
            │               │
     bridge_siblings        │              pull in paragraphs the top hits name
            └──────┬────────┘
             route_merge                   top 40
                    │
           confidence_gate                 GATE — did both lanes rank the same doc first?
             ┌──────┴──────┐
         fast_lane        rerank           skip reranking | cross-encoder
             └──────┬──────┘
           final_selection                 top 10   <- the release policy watches this
```

HotpotQA questions need two different Wikipedia paragraphs. **Bridge** questions ("what
position was held by the woman who played X") can't be answered in one search — you find who
that person is, then search again with their name. **Comparison** questions name both subjects
outright and just need a wider single pass.

**Both routing decisions are deterministic.** No trained model, and neither reads ground
truth. `type` is an input attribute of the question. Lane agreement is exact arithmetic on
scores the pipeline already computed: fusion gives a document `1/(60+rank)` from each lane
that found it, so unanimous first place scores exactly `2/61` while the best any other
document can reach is `1/61 + 1/62`. The threshold sits between them. On this data it splits
53% / 47%.

## Baseline

400 questions, 51 seconds, zero errors.

```
stage  operator                recall@10   ndcg@10
0      bm25_lane                  0.7762    0.6991
0      dense_lane                 0.7863    0.7299
1      hybrid_fusion              0.8413    0.7583      fusion beats either lane alone
5      route_merge                0.8413    0.7583
8      final_selection            0.8750    0.8292      what the pipeline returns
```

Routing: 78% bridge / 22% comparison; 47% of questions reranked.

**Lineage completeness: 100%.** All 400 traces and all 24,482 candidates graded `recorded`.
The lineage accounting reconciles exactly with the metric: 400 questions × 2 gold documents =
800, and 700 retained + 86 dropped mid-pipeline + 14 never retrieved = 800, giving
700/800 = 0.875 — the stage-8 recall, arrived at independently.

---

## Scenario A — a legitimate improvement

Scenario D (below) showed gold documents being discarded by the branch merge's width. The
change: **merge width 40 → 100**.

```
hotpotqa_hybrid_dag|stage8|recall@10   PASS   +0.0088   CI [+0.0019, +0.0181]   n=400
  type=bridge       PASS   +0.0096   n=312
  type=comparison   PASS   +0.0057   n=88
  level=hard        PASS   +0.0088   n=400
```

The interval excludes zero, so the improvement is real. It concentrates in bridge questions,
which is what the mechanism predicts — only they run a second hop, so only they have
late-arriving candidates for a wider merge to rescue.

**What the verdict does not cover:** the cross-encoder now scores 100 candidates instead of
40. `PASS` means "quality did not regress", not "ship it". The policy guards recall, not cost.

## Scenario B — a regression that passes, and why that matters

The keyword lane is disabled. The operator stays in the graph and returns nothing, so both
runs keep identical measurement names — delete the node and the policy's guard would point at
a stage that exists in one run and not the other, and the comparison would fail for a
bookkeeping reason rather than a quality one.

**A metrics dashboard sees:** final recall up 3 points, p95 latency down 24%, total runtime
down 17%, every gate green. Ship it.

**retobs shows:**

```
stage                       baseline   no-bm25     delta
stage0 [bm25_lane]            0.7762    0.0000   -0.7762
stage0 [dense_lane]           0.7863    0.7863   +0.0000
stage1 hybrid_fusion          0.8413    0.7863   -0.0550   <- retrieval capability collapsed
stage7 [fast_lane]            0.4462    0.0000   -0.4462   <- this lane now serves nobody
stage7 [rerank]               0.4288    0.9050   +0.4763
stage8 final_selection        0.8750    0.9050   +0.0300   <- the only number a dashboard shows
```

| | baseline | no-bm25 |
|---|---|---|
| queries reranked | 187/400 (47%) | **400/400 (100%)** |
| median latency | 539 ms | **718 ms (+33%)** |

Retrieval got 5.5 points worse. The output held up only because reranking now runs on every
query instead of half of them. The confidence gate has become decorative. The pipeline is
single-source, paying 2.1× the reranking work and 33% more median latency, one component
failure away from having nothing.

retobs is **correct** to return `PASS` — the policy asks whether the output regressed, and it
did not. The per-stage view is what turns a green light into an informed decision.

## Scenario C — a contradiction in the provenance record

The embedding model is swapped to `all-MiniLM-L12-v2` while the manifest keeps recording the
baseline's `index_build_id`.

```
Verdict: BLOCK
promotion/release_identity_mismatch
  Runs differ on release identity field 'embedding_model_revision'.

stage8|recall@10   PASS   effect 0.0000   CI [-0.0175, +0.0188]
```

**Read the guard row.** The metrics are immaculate — dead flat, tight interval. A metrics-only
view says "no change, safe to merge". retobs computed the same numbers and then refused to
decide on them.

Being precise about what this is: **both runs are internally valid.** Each searched an index
built by its own model, and L6-vs-L12 on a fixed corpus is a legitimate A/B test. What is
broken is the *record* — it asserts one index was searched by two different embedding models,
which cannot be true. retobs cannot know which field is the lie, so it declines to decide.
This is a provenance contradiction, not invalid retrieval.

That is a realistic mistake: plenty of setups rebuild the index automatically on a model
change while `index_build_id` is a hand-maintained string nobody remembers to bump.

## Scenario C2 — what that check prevents

The dangerous version. Queries are encoded with `all-MiniLM-L12-v2` and searched against the
index still built by `all-MiniLM-L6-v2`. **Nothing errors** — both models emit 384-dimensional
vectors, so the search runs happily and compares vectors from two unrelated spaces.

Here the manifest is **entirely truthful**: the embedding model really did change, and the
index really was not rebuilt, so its id really is the baseline's.

```
stage0 dense_lane      0.7863 -> 0.6125    -0.1738   the vector lane is now near-noise
stage1 hybrid_fusion   0.8413 -> 0.7925    -0.0488   BM25 masks half the damage
stage8 final           0.8750 -> 0.8538    -0.0212   reranking masks most of the rest

Verdict: BLOCK   (promotion/release_identity_mismatch)
stage8|recall@10   HOLD   -0.0212   CI [-0.0394, -0.0025]
```

The quality guard alone could only reach `HOLD` — the interval straddles the 2-point
tolerance, so the statistics can prove neither that it is within tolerance nor that it is not.
**The identity check decided what the metrics could not.** Meanwhile the vector lane, the
thing that actually broke, lost 17 points, and the healthy half of the hybrid pipeline hid it.

## Scenario D — why one query failed

Selected by evidence, not by eye (`inspect_run.py --pick`): a bridge question at `hard` level,
with complete tracing, that actually lost a gold document.

> *In what year was the British actress who starred in a film adaptation of a series of eight
> children's books written by P. L. Travers born?*
> gold: `mary_poppins`, `karen_dotrice`

```
bm25_lane        out 30    gold 1/2   ranks [1]
dense_lane       out 30    gold 2/2   ranks [2, 27]
hybrid_fusion    out 40    gold 1/2   !! dropped: karen_dotrice
type_gate        -> route 'bridge'
bridge_hop2      out 58    gold 2/2   ranks [1, 45]      <- the second hop recovered it
bridge_siblings  out 58    gold 2/2   ranks [1, 45]
route_merge      out 40    gold 1/2   !! dropped: karen_dotrice   <- and lost it again
rerank           out 10    gold 1/2
final_selection  out 10    gold 1/2

  karen_dotrice    relevant_dropped_at_stage  at hybrid_fusion
    dense_lane#27 -> bridge_hop2#45 -> bridge_siblings#45
```

Found by the vector lane, lost to merge truncation, **recovered by the two-hop search**, and
lost to merge truncation a second time. Only one lane found it, so its fusion score lost to
documents both lanes agreed on; then it landed at rank 45 against a width-40 cutoff.

That is the finding Scenario A acts on — and proves works.

---

## Files

```
build_corpus.py        HotpotQA -> corpus, queries, ground truth   (one command, reproducible)
pipeline.py            the eleven-operator DAG and its release identity
run.py                 execute one run and persist it
inspect_run.py         read a stored run: funnel, routing, lineage, single-query trace
make_reports.py        render every scenario report in JSON / Markdown / HTML
release-policy.yaml    the guard, the slices, the thresholds
run_demo.sh            all of the above, in order
reports/               generated output
DATA_PROVENANCE.md     licence, citation, how the ground truth was derived
CASE_STUDY.md          the narrative version
```

## Reproducing

```bash
./run_demo.sh
```

Rebuilds the dataset if `data/` is absent, runs five configurations, writes every report, and
prints the run ids. `data/` is regenerable and not committed; `dataset_manifest.json` records
the seed and a SHA-256 of each file so you can confirm you built the same corpus.

Measured on an M5 Max: **~4 minutes**, peak **3.2 GB** RAM, **~1.3 GB** on disk for five runs.

## Looking at it in the dashboard

```bash
retobs serve --db .retobs/demo.db
```

Then, with `<baseline>` from the run_demo.sh output:

| | |
|---|---|
| `#/runs` | the five runs |
| `#/compare` | select baseline + a candidate |
| `#/runs/<baseline>/queries/<query>` | the Scenario D lineage view |

The exact query id is printed at the end of `run_demo.sh` and in
`reports/scenario-d-lineage.txt`.

---

## Honest limitations

**This is not a competitive retrieval system.** Widths and models were chosen so the demo is
legible and cheap to rerun, not to maximise recall. Every scenario compares two runs sharing
the same components, so absolute quality cancels out.

**Ground truth is positive-only.** HotpotQA records which paragraphs support an answer, never
which are irrelevant. So ~2 documents per question can be judged and the other ~12,652 cannot,
and retrieved-then-dropped candidates are classified `unknown_relevance` rather than
`irrelevant_removed`. **That is retobs declining to guess, not a tracing failure.** The signal
for tracing health is `lineage_incomplete`, which is 0.0% here.

**`level` is `hard` for every question.** HotpotQA's validation split contains nothing else by
design. The slice is declared and reported, but its row necessarily mirrors the aggregate.
`type` is the axis that varies.

**Link expansion earns nothing.** `bridge_siblings` adds ~0.5 documents per query and moves
recall not at all — the corpus is a 12,654-paragraph sample, so most articles a paragraph
names are not in it. It was left in and left untuned after that was measured, because a stage
that costs latency and buys nothing is a useful thing for a per-stage view to reveal.

**One lineage requirement is genuinely unmet.** Reports carry
`lineage_diff/lineage_document_identity_partial` because this pipeline records no document
revisions or content hashes — and retobs' built-in fusion operator drops them anyway. That
finding is retobs correctly reporting a real limitation, and it is left visible.

**Ordering, for honesty.** The declared slice *sizes* were read from the baseline run, because
declaring a group that turns out to be empty forces a BLOCK for a sample-size reason unrelated
to the change under test. The regression *threshold* was fixed before any candidate run
existed and was never revisited.

## Data

HotpotQA (`hotpotqa/hotpot_qa`, `distractor`, validation split), CC BY-SA 4.0.
Yang et al., *HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering*,
EMNLP 2018. Full derivation in [DATA_PROVENANCE.md](DATA_PROVENANCE.md).
