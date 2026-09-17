# How retobs caught a regression a metrics dashboard would have shipped

Every number here comes from a run in `.retobs/demo.db`, regenerated on 2026-09-16 on the
post-0.6.0 build (branch metrics on served queries, strict counterfactual replay). Nothing is
illustrative, and where a result went against what we expected, it is reported that way.

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



## Act one: the regression that passes

This is the regression in the title, so it goes first. A change improved every number on the
dashboard and passed the release policy — bounded non-inferiority on the output, every declared
slice included — and still left the system worse for the people it was meant to help: slower
per query, single-source, with a whole branch of the architecture dead. None of that is visible
in the verdict. All of it is visible in the funnel underneath the verdict.

We disable the keyword lane — a realistic change, the kind someone makes to cut latency or
retire a component. Then we ask retobs whether it is safe to ship.

**It says** `PASS`**.** Final recall went *up*, by 3 points, with the interval excluding zero.
Every declared slice passes. p95 latency improved and total runtime dropped.

A metrics dashboard shows green across the board. **Ship it.**

Here is the same change, seen through the funnel:

```
stage                       baseline (n)      no-bm25 (n)       delta
stage0 [bm25_lane]            0.7762 (400)      lane disabled
stage0 [dense_lane]           0.7863 (400)      0.7863 (400)    +0.0000
stage1 hybrid_fusion          0.8413 (400)      0.7863 (400)    -0.0550
stage7 [fast_lane]            0.8380 (213)      served 0
stage7 [rerank]               0.9171 (187)      0.9050 (400)
stage8 final_selection        0.8750 (400)      0.9050 (400)    +0.0300
```

Branch rows are recall@10 on the queries that branch actually served, with the served count
beside each. (An earlier build scored every query a gate routed elsewhere as 0, which made the
rerank row read 0.43 → 0.91 and looked like the reranker had got better. It had not.)

Retrieval capability fell 5.5 points at the fusion stage. The output held up for one reason:
reranking went from 47% of queries to **100%**. On the 187 queries the baseline had reranked,
the candidate's reranker scores 0.890 — paired, no significant difference. The 3-point gain
comes from the other 213 queries, which the fast lane used to serve at 0.838 and the
cross-encoder now serves instead.


|                  | baseline  | keyword lane disabled |
| ---------------- | --------- | --------------------- |
| queries reranked | 187 / 400 | **400 / 400**         |
| median latency   | 608 ms    | **865 ms**            |


The reranking counts come from the run record and reproduce exactly. The latency figures do not:
they are wall-clock measurements from a single unseeded run on one laptop. Across three reruns
on the same machine (539 → 718, 518 → 816, 608 → 865 ms) the median always got worse and p95
always improved; total runtime dropped on two of the three and rose on the third (317 s → 352 s
on the run reported here, made with OpenMP pinned to one thread). Read the sign of the median,
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



## Act two: the tool finds something

Act one was a verdict that needed the evidence underneath it. The next two acts run the other
way: start from one failed query, find the mechanism, fix it, and prove the fix on the same
evidence.

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

## Act three: the fix, and the proof

Merge width 40 → 100. One number.

```
hotpotqa_hybrid_dag|stage8|recall@10   PASS   +0.0088   CI [+0.0019, +0.0181]   n=400
```

The confidence interval excludes zero, so this is a real improvement rather than noise. And
the slice breakdown confirms the mechanism rather than just the outcome:


|                                    | effect      |
| ---------------------------------- | ----------- |
| bridge questions (two-hop)         | **+0.0096** |
| comparison questions (single-pass) | +0.0057     |


The gain is consistent with the mechanism: the bridge-question interval excludes zero while the
comparison-question interval touches it, though the two intervals overlap, so the data do not
prove the slices differ. The second hop is the only place a wider merge could
possibly help. Diagnosis, fix, verification, all on the same evidence.

Worth saying plainly: reranking now scores 100 candidates instead of 40. `PASS` means quality
did not regress. It does not mean the trade is worth it — the policy guards recall, not cost.
That call stays with a human, which is the correct division of labour.

---



## What the whole thing adds up to


|                        | a metrics dashboard says | retobs says                                                                       |
| ---------------------- | ------------------------ | --------------------------------------------------------------------------------- |
| **A** wider merge      | recall +0.9pt            | real (CI excludes zero), concentrated in two-hop questions, costs 2.5× reranking  |
| **B** keyword lane off | recall +3pt — ship it    | output improved; retrieval collapsed 5.5pt, reranking cost doubled, a branch died |
| **C** model swapped    | no change — merge it     | the provenance contradicts itself; these numbers cannot decide anything           |
| **C2** stale index     | −2pt, borderline         | the vector lane lost 17pt and the healthy half hid it                             |
| **D** one bad query    | recall 0.5               | found at rank 27, dropped by merge, recovered by the second hop, dropped again    |


Four of those five are cases where the headline number is either reassuring or ambiguous, and  
the thing you needed to know is somewhere else. The two model-swap scenarios are in the
appendix below.

Reproduce all of it with `./run_demo.sh` — about four minutes, no API keys.

---



## Appendix: the comparison that should not be made

The remaining two scenarios are about something more basic than "is this better": *is this
comparison meaningful at all?* They sit outside the three acts because they are not about a
verdict being right or wrong, but about whether a verdict should be given.

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
