# How retobs caught a regression a metrics dashboard would have shipped

Every number here comes from a run in `.retobs/demo.db`. Nothing is illustrative, and where a
result went against what we expected, it is reported that way.

Two classes of number appear below, and they carry different guarantees. Quality metrics and their
confidence intervals are seeded (`seed: 17`, 2000 resamples) and reproduce **exactly** — an
independent rerun matched every effect size, interval, verdict, and paired sample count. Latency
and wall-clock figures are not seeded and are machine-dependent: their direction reproduces, their
digits do not. Latency claims are labelled where they appear.

---

## The setup

A hybrid retrieval pipeline over 12,654 Wikipedia paragraphs, answering 400 HotpotQA
questions. Two search lanes — keyword and vector — merged by rank fusion. Questions needing
two hops of reasoning take a different path from questions that name both their subjects.
Where the two lanes disagree about the best document, a cross-encoder reranks; where they
agree, the pipeline saves the work.

Eleven operators. The kind of pipeline that is genuinely hard to reason about, because a
change anywhere can be masked or amplified anywhere else.

Baseline: **recall@10 of 0.875**, and roughly 50 seconds of wall clock for 400 questions.

---

## Act one: the tool finds something

Scenario D asks a question no aggregate can answer: *why did this particular query fail?*

The query picked — automatically, by looking for a two-hop question with complete tracing that
actually lost a gold document — was:

> *In what year was the British actress who starred in a film adaptation of a series of eight
> children's books written by P. L. Travers born?*

Answering it needs two paragraphs: the film, and the actress. The pipeline returned one.

A metrics dashboard reports that as **recall 0.5 on query 5abccf67** and stops. Here is what
retobs reported instead:

```
bm25_lane        gold 1/2   ranks [1]
dense_lane       gold 2/2   ranks [2, 27]
hybrid_fusion    gold 1/2   !! dropped: karen_dotrice
bridge_hop2      gold 2/2   ranks [1, 45]      <- the second hop found it again
route_merge      gold 1/2   !! dropped: karen_dotrice
final_selection  gold 1/2
```

The actress's paragraph was found by the vector lane at rank 27. The merge step kept 40
candidates, but ranked it below documents that *both* lanes had agreed on, and dropped it.
Then the two-hop search — working exactly as designed — went and found it again at rank 45.
And the second merge, also keeping 40, dropped it a second time.

Not "retrieval is bad". Specifically: **your two-hop search is doing its job and your merge
width is throwing away what it finds.**

## Act two: the fix, and the proof

Merge width 40 → 100. One number.

```
hotpotqa_hybrid_dag|stage8|recall@10   PASS   +0.0088   CI [+0.0019, +0.0181]   n=400
```

The confidence interval excludes zero, so this is a real improvement rather than noise. And
the slice breakdown confirms the mechanism rather than just the outcome:

| | effect |
|---|---|
| bridge questions (two-hop) | **+0.0096** |
| comparison questions (single-pass) | +0.0057 |

The gain concentrates where the second hop runs — which is the only place a wider merge could
possibly help. Diagnosis, fix, verification, all on the same evidence.

Worth saying plainly: reranking now scores 100 candidates instead of 40. `PASS` means quality
did not regress. It does not mean the trade is worth it — the policy guards recall, not cost.
That call stays with a human, which is the correct division of labour.

---

## Act three: the regression that passes

Now the part that matters.

We disable the keyword lane — a realistic change, the kind someone makes to cut latency or
retire a component. Then we ask retobs whether it is safe to ship.

**It says `PASS`.** Final recall went *up*, by 3 points, with the interval excluding zero.
Every declared slice passes. p95 latency improved and total runtime dropped.

A metrics dashboard shows green across the board. **Ship it.**

Here is the same change, seen through the funnel:

```
stage                       baseline   no-bm25     delta
stage0 [bm25_lane]            0.7762    0.0000   -0.7762
stage0 [dense_lane]           0.7863    0.7863   +0.0000
stage1 hybrid_fusion          0.8413    0.7863   -0.0550
stage7 [fast_lane]            0.4462    0.0000   -0.4462
stage7 [rerank]               0.4288    0.9050   +0.4763
stage8 final_selection        0.8750    0.9050   +0.0300
```

Retrieval capability fell 5.5 points at the fusion stage. The output held up for one reason:
reranking went from 47% of queries to **100%**.

| | baseline | keyword lane disabled |
|---|---|---|
| queries reranked | 187 / 400 | **400 / 400** |
| median latency | 539 ms | **718 ms** |

The reranking counts come from the run record and reproduce exactly. The latency figures do not:
they are wall-clock measurements from a single unseeded run on one laptop. The *direction*
reproduces on every rerun — median latency gets worse, p95 improves, total runtime drops — but the
exact milliseconds move with machine load. A later rerun measured 518 ms → 816 ms. Read the sign,
not the digits.

Three things a single number cannot tell you:

1. **The pipeline is now single-source.** One retrieval method, no fallback. The redundancy
   that made it robust is gone.
2. **The confidence gate is dead.** The fast lane serves zero queries. A whole branch of the
   architecture is now decorative, and nobody would have noticed.
3. **The saving didn't materialise.** Median latency got worse, because every query now pays
   the reranking cost that used to be spent selectively.

The output number improved. The system got more fragile, more expensive per query, and lost
half its architecture. **This is what "green metrics, worse system" looks like**, and it is
not a contrived example — it is what happened when we ran the change.

retobs returning `PASS` is not a failure. The policy asked whether the output regressed; it
did not. What retobs adds is the funnel underneath the verdict, which turns a green light into
a decision someone can actually make.

---

## Act four: the comparison that should not be made

The last two scenarios are about something more basic than "is this better": *is this
comparison meaningful at all?*

**An engineer swaps the embedding model** and the manifest keeps recording the old index id.
retobs blocks:

```
Verdict: BLOCK
  Runs differ on release identity field 'embedding_model_revision'.

stage8|recall@10   PASS   effect 0.0000   CI [-0.0175, +0.0188]
```

Look at that guard row. The metrics are **immaculate** — dead flat, tight interval. Any
metrics-only view says "no change, merge it". retobs computed exactly the same numbers and
then declined to decide on them, because the record asserts that one index was searched by two
different embedding models, which cannot be true. It cannot know which field is wrong, so it
refuses to guess.

**Then the version that check exists to prevent.** Same model swap — but this time the index
is genuinely never rebuilt. Queries encoded by the new model, searched against the old model's
vectors. Both produce 384-dimensional vectors, so nothing errors. The search runs happily,
comparing vectors from two unrelated spaces.

```
stage0 dense_lane      0.7863 -> 0.6125    -0.1738    the vector lane is now near-noise
stage1 hybrid_fusion   0.8413 -> 0.7925    -0.0488    keyword search masks half the damage
stage8 final           0.8750 -> 0.8538    -0.0212    reranking masks most of the rest

stage8|recall@10   HOLD   -0.0212   CI [-0.0394, -0.0025]
Verdict: BLOCK
```

The component that broke lost **17 points**. By the time that reached the output it was 2
points — small enough that the statistics could only manage `HOLD`: the interval straddles the
tolerance, so it can prove neither that the damage is acceptable nor that it isn't.

**The identity check decided what the metrics could not.** And here the manifest was entirely
truthful — the model really did change, the index really wasn't rebuilt. retobs didn't catch a
lie. It caught a combination of facts that makes a comparison meaningless.

That is the property that makes the other verdicts worth anything. A tool that always produces
an answer gives you no way to tell a real answer from a confidently wrong one.

---

## What the whole thing adds up to

| | a metrics dashboard says | retobs says |
|---|---|---|
| **A** wider merge | recall +0.9pt | real (CI excludes zero), concentrated in two-hop questions, costs 2.5× reranking |
| **B** keyword lane off | recall +3pt — ship it | output improved; retrieval collapsed 5.5pt, reranking cost doubled, a branch died |
| **C** model swapped | no change — merge it | the provenance contradicts itself; these numbers cannot decide anything |
| **C2** stale index | −2pt, borderline | the vector lane lost 17pt and the healthy half hid it |
| **D** one bad query | recall 0.5 | found at rank 27, dropped by merge, recovered by the second hop, dropped again |

Four of those five are cases where the headline number is either reassuring or ambiguous, and
the thing you needed to know is somewhere else.

## What this demo does not show

Being straight about the boundaries:

- **It is not a competitive retrieval system.** Widths and models were chosen for legibility
  and cheap reruns. Every scenario compares two runs with the same components, so absolute
  quality cancels.
- **It does not prove retobs is easy to adopt.** This pipeline was built inside the retobs
  repository against its internals. Whether an agent can wire retobs into someone else's
  project from one instruction is a separate question, tested separately, and not answered
  here.
- **Ground truth is positive-only**, so most retrieved documents are `unknown_relevance` — not
  a tracing failure, but a limit on how much the lineage read-out can say. Tracing health
  (`lineage_incomplete`) is 0.0%.
- **One lineage requirement is genuinely unmet** and left visible in every report: this
  pipeline records no document content hashes, so `lineage_document_identity_partial` fires.
  That is retobs correctly reporting a real limitation.

Reproduce all of it with `./run_demo.sh` — about four minutes, no API keys.
