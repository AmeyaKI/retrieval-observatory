# Benchmark Results — retobs (v0.1.2)

Benchmarked **4 independent retrieval pipelines** across 3 BEIR datasets (1,271 total queries). All numbers are from committed JSON exports in [results/](results/). Regenerate with `python scripts/bench_analytics.py`.

---

## At a Glance


| Dataset                     | Queries | Corpus      | Best pipeline | NDCG@10   | vs BM25 baseline |
| --------------------------- | ------- | ----------- | ------------- | --------- | ---------------- |
| NFCorpus (biomedical)       | 323     | 3,633 docs  | dense_only    | **0.310** | +17.6%           |
| SciFact (scientific claims) | 300     | 5,183 docs  | dense_only    | **0.640** | +17.7%           |
| FiQA (financial QA)         | 648     | 57,638 docs | dense_only    | **0.369** | +132%            |


Dense retrieval (`all-MiniLM-L6-v2`) is Pareto-optimal on SciFact and FiQA — it beats every other pipeline on quality *and* is cheaper to run than reranking.

---

## Full Results by Dataset

### NFCorpus — Biomedical Nutrition Queries (323 queries)


| Pipeline     | NDCG@10   | Recall@10 | MRR   | Latency P50 | Pareto |
| ------------ | --------- | --------- | ----- | ----------- | ------ |
| bm25         | 0.264     | 0.119     | 0.468 | 1.1ms       | ✓      |
| dense_only   | **0.310** | **0.153** | 0.510 | 4.8ms       | ✓      |
| rrf_hybrid   | 0.304     | 0.140     | 0.519 | 7.1ms       | —      |
| bm25__rerank | 0.310     | 0.138     | 0.530 | 1,098ms     | —      |


**Finding:** All 4 pipelines have overlapping 95% CIs on NFCorpus — no statistically dominant winner. The cross-encoder reranker matches dense quality at **228× higher latency**, making it Pareto-dominated. BM25 at 1.1ms is the efficiency winner.

### SciFact — Scientific Fact Verification (300 queries)


| Pipeline     | NDCG@10   | Recall@10 | MRR   | Latency P50 | Pareto |
| ------------ | --------- | --------- | ----- | ----------- | ------ |
| bm25         | 0.544     | 0.669     | 0.514 | 6.6ms       | —      |
| dense_only   | **0.640** | **0.787** | 0.603 | 5.6ms       | ✓      |
| rrf_hybrid   | 0.623     | 0.733     | 0.602 | 12.5ms      | —      |
| bm25__rerank | 0.628     | 0.731     | 0.602 | 1,097ms     | —      |


**Finding:** Dense-only is the sole Pareto-optimal pipeline. It outperforms BM25 by **+17.7% NDCG@10** and is *faster* than BM25 on this corpus (5.6ms vs 6.6ms). The CI gap between BM25 and dense is non-overlapping — a statistically clear win.

### FiQA — Financial Question Answering (648 queries, 57k-doc corpus)


| Pipeline     | NDCG@10   | Recall@10 | MRR   | Latency P50 | Pareto |
| ------------ | --------- | --------- | ----- | ----------- | ------ |
| bm25         | 0.159     | 0.204     | 0.207 | 77ms        | —      |
| dense_only   | **0.369** | **0.441** | 0.454 | 8.8ms       | ✓      |
| rrf_hybrid   | 0.290     | 0.367     | 0.374 | 95.8ms      | —      |
| bm25__rerank | 0.260     | 0.296     | 0.342 | 1,166ms     | —      |


**Finding:** FiQA is the starkest result. Dense retrieval outperforms BM25 by **+132% NDCG@10** (0.369 vs 0.159) and is **~9× faster** than BM25 on this large corpus (8.8ms vs 77ms). BM25 struggles with the paraphrastic phrasing typical of financial queries. Non-overlapping CIs confirm this is a robust finding.

---



## Stage Attribution: Does Reranking Pay Off?

The bm25 → bm25__rerank pipeline pair shows what cross-encoder reranking adds on top of BM25 candidates.


| Dataset  | NDCG@10 gain  | Latency added | Verdict                                                             |
| -------- | ------------- | ------------- | ------------------------------------------------------------------- |
| NFCorpus | +0.046 (+17%) | +1,097ms      | Dense achieves same quality at 228× lower latency                   |
| SciFact  | +0.084 (+15%) | +1,091ms      | Dense beats reranked BM25 at 195× lower latency                     |
| FiQA     | +0.101 (+63%) | +1,089ms      | Largest gain, but dense still 42% better NDCG at 133× lower latency |


Cross-encoder reranking recovers real quality on top of BM25, but across all three datasets `dense_only` achieves the same or better NDCG at a fraction of the latency cost.

---



## Query Difficulty Distribution

Difficulty buckets are predicted by a corpus-specific classifier trained on post-hoc recall labels.


| Dataset  | Easy      | Medium    | Hard      | Discriminative |
| -------- | --------- | --------- | --------- | -------------- |
| NFCorpus | 13 (4%)   | 107 (33%) | 183 (57%) | 20 (6%)        |
| SciFact  | 216 (72%) | —         | 14 (5%)   | 70 (23%)       |
| FiQA     | 122 (19%) | 118 (18%) | 113 (17%) | 295 (46%)      |


NFCorpus is overwhelmingly hard (specialized biomedical vocabulary). SciFact is predominantly easy. FiQA is the most heterogeneous with 46% "discriminative" queries where pipelines split.

**Classifier calibration on NFCorpus:** Predicted-hard queries achieve Recall@10 = 0.093; predicted-easy queries achieve 0.635 — the model correctly separates retrievable from non-retrievable queries before running retrieval.

---



## Failure Label Breakdown

Labels are assigned per query by retobs's diagnostic layer.


| Label            | NFCorpus | SciFact | FiQA | What it means                                         |
| ---------------- | -------- | ------- | ---- | ----------------------------------------------------- |
| candidate_miss   | 84       | 63      | 288  | Relevant doc never appeared in any stage's candidates |
| lexical_mismatch | 43       | 49      | 217  | Vocabulary gap caused miss (BM25-specific)            |
| id_or_qrel_issue | 41       | 14      | 71   | Annotation artifact (doc ID absent from corpus)       |


FiQA's 288 candidate misses (44% of queries) explain BM25's poor performance — the financial corpus requires semantic understanding that bag-of-words retrieval cannot provide.

---



## Artifacts and Reproducibility

Full per-dataset JSON exports and dashboard screenshots:


| Folder                                               | Contents                                              |
| ---------------------------------------------------- | ----------------------------------------------------- |
| [results/nfcorpus/](results/nfcorpus/)               | metrics, diagnostics, stage attribution, run metadata |
| [results/scifact/](results/scifact/)                 | same                                                  |
| [results/fiqa/](results/fiqa/)                       | same                                                  |
| [results/cohere_nfcorpus/](results/cohere_nfcorpus/) | BM25 + Cohere reranker comparison (partial run)       |
| [results/screenshots/](results/screenshots/)         | Dashboard visualizations                              |


Each folder contains `metrics.json`, `diagnostics.json`, `stage_contributions.json`, and `run_meta.json`.

Cross-dataset aggregate: [results/analytics_extract.json](results/analytics_extract.json)

Full sweep configs, statistical methodology, and Pareto analysis: [results/BENCHMARK_ANALYSIS.md](results/BENCHMARK_ANALYSIS.md)

To reproduce from scratch:

```bash
pip install -e ".[demo,dashboard,dense]"
./scripts/run_beir_publish.sh full-sweep
python scripts/bench_analytics.py > results/analytics_extract.json
```

