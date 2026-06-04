# Retrieval Observatory — Case Study: BEIR Datasets Benchmark Analysis

Analysis generated from SQLite benchmark stores (not hand-entered numbers). Publication sweeps use dataset-specific databases referenced in [configs/beir_publish/](../configs/beir_publish/) and in `run_meta.json` under each `results/<dataset>/` export folder.

Machine-readable aggregates: [analytics_extract.json](analytics_extract.json). Recompute with:

```bash
python scripts/bench_analytics.py > results/analytics_extract.json
```


| Dataset           | SQLite path                          | Run ID     | Experiment                     |
| ----------------- | ------------------------------------ | ---------- | ------------------------------ |
| NFCorpus          | `.retobs/publish_sweep_nfcorpus.db`  | `37d3a79c` | `beir-publish-sweep-nfcorpus`  |
| SciFact           | `.retobs/publish_sweep_scifact.db`   | `49b423cf` | `beir-publish-sweep-scifact`   |
| FiQA              | `.retobs/publish_sweep_fiqa.db`      | `0784ed30` | `beir-publish-sweep-fiqa`      |
| NFCorpus (Cohere) | `.retobs/publish_cohere_nfcorpus.db` | `a6dad22f` | `beir-publish-cohere-nfcorpus` |


---

## Motivation

### Why these three datasets?


| Dataset      | Domain                      | What it stresses                                                                       |
| ------------ | --------------------------- | -------------------------------------------------------------------------------------- |
| **NFCorpus** | Biomedical nutrition claims | Sparse relevance labels, specialized vocabulary — lexical vs dense tradeoffs are tight |
| **SciFact**  | Scientific fact-checking    | Short claim–evidence pairs; dense retrieval often beats BM25 on semantic similarity    |
| **FiQA**     | Financial QA                | Large corpus (57k docs), diverse phrasing — largest quality gap between BM25 and dense |


Each dataset tests different retrieval properties. Together they span sparse-label biomedical search, scientific claim verification, and open-domain financial QA.

### What the four pipelines represent

These are **four independent pipelines**, not a single ablation chain:


| Pipeline       | Design choice                                                          |
| -------------- | ---------------------------------------------------------------------- |
| `bm25`         | Lexical baseline (`rank-bm25`, top-100)                                |
| `dense_only`   | Bi-encoder retrieval (`all-MiniLM-L6-v2`, top-100)                     |
| `rrf_hybrid`   | Reciprocal rank fusion of BM25 + dense (`rrf_k=60`)                    |
| `bm25__rerank` | BM25 top-100 → cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`, top-10) |


Stage attribution (bm25 → bm25__rerank) uses the prefix pair only. Verdict and Pareto analysis compare all four pipelines in parallel.

### Questions this sweep was designed to answer

Using RETOBS to benchmark and visualize different RAG stages:

1. **Which first-stage retriever should you default to?** BM25, dense, or hybrid?
2. **Is cross-encoder reranking worth the latency cost** when you keep a BM25 candidate pool?
3. **How much does query difficulty vary**, and can you predict it before running retrieval?

Configs: [configs/beir_publish/](../configs/beir_publish/). Reproduce full sweep: `./scripts/run_beir_publish.sh full-sweep`.

---

## Setup

Metrics are **per-query** NDCG@10, Recall@10, and MRR on the **final pipeline stage**. Latency is end-to-end pipeline time (P50/P95). 95% bootstrap CIs via paired resampling (5,000 iterations).


| Dataset                       | Queries             | Corpus docs | `cache_results` | Git commit |
| ----------------------------- | ------------------- | ----------- | --------------- | ---------- |
| BEIR NFCorpus                 | 323                 | 3,633       | `true`          | `0991e64`  |
| BEIR SciFact                  | 300                 | 5,183       | `true`          | `0991e64`  |
| BEIR FiQA                     | 648                 | 57,638      | `true`          | `0991e64`  |
| BEIR NFCorpus (Cohere rerank) | 323 (155 rerank OK) | 3,633       | `true`          | `0991e64`  |


Environment (manifest): macOS arm64, Python 3.12.4, `retrieval-observatory==0.1.0`, `faiss-cpu==1.14.2`, `sentence-transformers==5.5.1`, `rank-bm25==0.2.2`. **Temporal recall metrics are not present** in these runs.

Query-difficulty **predictions** (3-class: easy / medium / hard) are attached for NFCorpus sweep and Cohere runs only.

---

## Cross-dataset summary

NDCG@10 (mean) and P50 latency (ms) across all three full sweeps:


| Dataset      | bm25           | dense_only         | rrf_hybrid      | bm25__rerank     | Pareto optimal       |
| ------------ | -------------- | ------------------ | --------------- | ---------------- | -------------------- |
| **NFCorpus** | 0.264 / 1.1 ms | **0.310** / 4.8 ms | 0.304 / 7.1 ms  | 0.310 / 1,098 ms | `bm25`, `dense_only` |
| **SciFact**  | 0.544 / 6.6 ms | **0.640** / 5.6 ms | 0.623 / 12.5 ms | 0.628 / 1,097 ms | `dense_only` only    |
| **FiQA**     | 0.159 / 77 ms  | **0.369** / 8.8 ms | 0.290 / 96 ms   | 0.260 / 1,166 ms | `dense_only` only    |


On **SciFact and FiQA**, `dense_only` is the sole Pareto-optimal configuration — no other pipeline is simultaneously better on quality and faster. On **NFCorpus**, BM25 and dense split the frontier: BM25 wins on latency; dense wins on quality.

> **NFCorpus caveat:** NDCG@10 bootstrap CIs overlap among dense, rerank, and RRF. Do not claim a single NDCG winner on that dataset.

Quality–Latency Tradeoff — NFCorpus

Quality–Latency Tradeoff — FiQA

---

## Per-dataset results

### NFCorpus (323 queries)


| Pipeline       | NDCG@10   | Recall@10 | MRR       | P50 latency (ms) |
| -------------- | --------- | --------- | --------- | ---------------- |
| `bm25`         | 0.264     | 0.119     | 0.468     | 1.1              |
| `bm25__rerank` | 0.310     | 0.138     | **0.530** | 1,098            |
| `dense_only`   | **0.310** | **0.153** | 0.510     | 4.8              |
| `rrf_hybrid`   | 0.304     | 0.140     | 0.519     | 7.1              |


95% bootstrap CIs: NDCG@10 — BM25 [0.232, 0.297], rerank [0.276, 0.344], dense [0.277, 0.344], RRF [0.271, 0.339]. **All pairwise NDCG@10 CIs overlap** among the three non-BM25 pipelines.

### SciFact (300 queries)


| Pipeline       | NDCG@10   | Recall@10 | MRR       | P50 latency (ms) |
| -------------- | --------- | --------- | --------- | ---------------- |
| `bm25`         | 0.544     | 0.669     | 0.514     | 6.6              |
| `bm25__rerank` | 0.628     | 0.731     | 0.602     | 1,097            |
| `dense_only`   | **0.640** | **0.787** | **0.603** | 5.6              |
| `rrf_hybrid`   | 0.623     | 0.733     | 0.602     | 12.5             |


NDCG@10 CIs: BM25 [0.495, 0.592], dense [0.595, 0.684]. **BM25 vs `dense_only` intervals do not overlap**.

### FiQA (648 queries)


| Pipeline       | NDCG@10   | Recall@10 | MRR       | P50 latency (ms) |
| -------------- | --------- | --------- | --------- | ---------------- |
| `bm25`         | 0.159     | 0.204     | 0.207     | 77.1             |
| `bm25__rerank` | 0.260     | 0.296     | 0.342     | 1,166            |
| `dense_only`   | **0.369** | **0.441** | **0.454** | 8.8              |
| `rrf_hybrid`   | 0.290     | 0.367     | 0.374     | 95.8             |


**No NDCG@10 CI overlaps** between BM25 and any other pipeline; dense vs rerank and dense vs RRF are also disjoint. FiQA is the most separable benchmark in this sweep.

---

## Pareto frontier

**Definition:** A pipeline is Pareto-optimal if no other pipeline has both higher NDCG@10 and lower P50 latency.


| Dataset  | Pareto-optimal pipelines | Practitioner takeaway                                                    |
| -------- | ------------------------ | ------------------------------------------------------------------------ |
| NFCorpus | `bm25`, `dense_only`     | Choose BM25 for sub-ms latency budgets; dense for quality at ~5 ms P50   |
| SciFact  | `dense_only` only        | Dense is strictly better on both axes — BM25 is faster but dominated     |
| FiQA     | `dense_only` only        | Dense delivers +132% NDCG@10 vs BM25 at ~9× lower latency than reranking |


`bm25__rerank` and `rrf_hybrid` are **Pareto-dominated** on SciFact and FiQA: they cost more latency without beating dense on quality. On NFCorpus, rerank matches dense NDCG but at ~230× the latency of dense.

Quality per ms (NDCG@10 / mean latency × 1000): NFCorpus — BM25 **177.6**, dense **56.3**, rerank **0.28**; SciFact — dense **102.1**, BM25 **78.6**; FiQA — dense **41.9**, BM25 **2.0**.

---

## Reranker recovery vs reordering

On all three full sweeps, `bm25__rerank` increases **both** NDCG@10 and Recall@10 vs stage-0 BM25 (same 100-doc candidate pool). Diagnostic mode is `**recovery`** — the cross-encoder surfaces relevant documents that BM25 ranked outside the top 10, not just reorders existing top-10 hits.


| Dataset  | NDCG@10 Δ | Recall@10 Δ | Latency multiplier vs BM25 |
| -------- | --------- | ----------- | -------------------------- |
| NFCorpus | +17.5%    | +16.0%      | ~988×                      |
| SciFact  | +15.5%    | +9.3%       | ~166×                      |
| FiQA     | +63.3%    | +45.3%      | ~15×                       |


**Why this matters:** Reranking is justified when you need recall gains from an existing BM25 pool and can pay ~1.1 s/query P50 on CPU. It is **not** a substitute for dense retrieval on FiQA (dense NDCG 0.369 vs rerank 0.260).

Stage Attribution: bm25 → bm25__rerank

Cross-encoder stage P50 ≈ **1,090 ms** across datasets (scoring 100 BM25 candidates on CPU).

---

## Query difficulty classifier

The classifier predicts whether a query will be hard for retrieval **before** running your pipeline, using only query text. Labels come from post-hoc diagnostics (mean Recall across pipelines on the corpus) — models are **dataset-specific**.

### Training

- **Model:** `HistGradientBoostingClassifier` (200 iterations, max depth 6)
- **Features:** 14 query-text features — token count, lexical density, temporal anchors, negation, question type one-hot, etc. ([classifier/features.py](../retrieval_observatory/classifier/features.py))
- **Validation:** 5-fold `StratifiedGroupKFold` CV (grouped by normalized query text)
- **Training data:** Full NFCorpus sweep (323 queries) → easy 13 / medium 107 / hard 203

### Calibration metrics (NFCorpus)


| Metric                                   | Value     |
| ---------------------------------------- | --------- |
| CV accuracy (vs 3-class training labels) | **80.8%** |
| Mean multi-class Brier score             | **0.097** |


### Predicted vs actual Recall@10 (monotonicity proof)

Mean Recall@10 grouped by **predicted** difficulty bucket (all pipelines, NFCorpus):


| Predicted bucket | Mean Recall@10 |
| ---------------- | -------------- |
| easy             | **0.635**      |
| medium           | **0.151**      |
| hard             | **0.093**      |


Monotonic decline across buckets validates the classifier as a **routing signal** — route predicted-easy queries to cheap BM25, reserve dense/reranked paths for predicted-hard traffic.

For comparison, **actual** difficulty buckets on BM25 alone: easy (n=13) mean Recall@10 **0.767** vs hard (n=183) **0.028** — gap **0.739**.

Classifier Calibration

**Caveat:** The classifier predicts observatory difficulty under *your* pipelines on *your* corpus — not intrinsic question hardness. Train and evaluate on the same dataset.

Train: `retobs classifier train --dataset beir/nfcorpus --db .retobs/publish_sweep_nfcorpus.db`

---

## Cohere rerank (partial run)

> **⚠ Incomplete run:** Only **155/323 queries (48%)** completed Cohere rerank; **168 errored** (likely Cohere free-tier API rate limits).
>
> Directional lift on the successful subset: NDCG@10 **0.280 → 0.329** (+17.3% relative), Recall@10 **0.126 → 0.151** (+20.2%). This is **suggestive but not publication-grade** until a clean rerun with `--no-cache` and sufficient API quota.


| Pipeline              | NDCG@10 | Recall@10 | Queries scored |
| --------------------- | ------- | --------- | -------------- |
| `bm25`                | 0.264   | 0.119     | 323            |
| `bm25__cohere_rerank` | 0.329*  | 0.151*    | **155**        |


Successful rerank stage P50 ≈ **582 ms** vs BM25 P50 ≈ **2.1 ms** on the matched subset (~278× rerank-stage cost).

---

## Findings by practitioner decision

### 1. Choosing your first-stage retriever

- **SciFact & FiQA:** `dense_only` is the clear default. NDCG gains of +17.7% (SciFact) and +132% (FiQA) vs BM25; bootstrap CIs do not overlap.
- **NFCorpus:** Dense, rerank, and RRF tie on NDCG (~0.310) with overlapping CIs. Dense wins on Recall@10 (0.153 vs 0.138); rerank wins on MRR (0.530 vs 0.510). No single NDCG winner — choose by secondary metric and latency budget.
- **Hybrid RRF** lands between BM25 and dense but is Pareto-dominated by `dense_only` on SciFact and FiQA.

### 2. Whether to add reranking

- Cross-encoder reranking **recovers** relevant docs from the BM25 pool (+Recall@10 on all datasets) but costs ~1.1 s/query P50 on CPU.
- On FiQA, reranking cannot close the gap to dense-only (0.260 vs 0.369 NDCG@10).
- `reranker_drop` appears 28 times on NFCorpus — reranking sometimes hurts after BM25 had the doc in the pool.

### 3. Handling query variance

- Query difficulty spread is enormous: NFCorpus easy Recall@10 **0.767** vs hard **0.028**.
- The pre-retrieval classifier (80.8% accuracy, Brier 0.097) separates predicted buckets with monotonic Recall@10 (0.635 → 0.151 → 0.093).
- Failure modes are dominated by `**candidate_miss`** and `**lexical_mismatch`** — not semantic_mismatch labels in these aggregates.

---

## Query difficulty detail (BM25 diagnostics)


| Dataset  | Bucket         | n   | Mean Recall@10 |
| -------- | -------------- | --- | -------------- |
| NFCorpus | easy           | 13  | 0.767          |
| NFCorpus | medium         | 107 | 0.205          |
| NFCorpus | hard           | 183 | 0.028          |
| NFCorpus | discriminative | 20  | 0.071          |
| SciFact  | easy           | 216 | 0.883          |
| SciFact  | hard           | 14  | 0.000          |
| FiQA     | easy           | 122 | 0.646          |
| FiQA     | hard           | 113 | 0.001          |


SciFact has very few “hard” queries (14); hard-bin means are noisy.

---

## Limitations

- **Sample size and domain:** Three BEIR subsets on CPU-oriented configs. Do not extrapolate to production corpora, multilingual data, or GPU-served encoders without re-measurement.
- **Results sharded per experiment:** Always read `run_manifests` / `results/*/run_meta.json` for authoritative paths.
- **Caching:** Full sweeps ran with `cache_results: true`. Re-runs may reuse staged outputs; use `--no-cache` for audit reruns.
- **Cohere run incomplete:** Only 155/323 (48%) queries completed. Reported lifts are on the successful subset only.
- **Statistical reporting:** Bootstrap CI overlap is conservative for ranking similar pipelines (NFCorpus dense vs rerank). Use overlapping CIs to avoid overclaiming.
- **Temporal metrics:** Not computed in these stores.

---

## Implications for practitioners

For **latency-sensitive** workloads, **BM25 alone** stays Pareto-relevant on NFCorpus (1 ms-scale P50) but leaves large Recall@10 gaps on hard queries. `**dense_only`** is the quality–latency sweet spot on SciFact and FiQA (~6–9 ms P50 with large NDCG gains). **Cross-encoder reranking** is justified when you need recall gains from the same BM25 pool and can pay ~1.1 s/query. **Hybrid RRF** is Pareto-dominated by dense on SciFact and FiQA. Use **query-difficulty predictions** to route cheap models for predicted-easy queries. Re-run Cohere with `--no-cache` and complete API stages before drawing conclusions.