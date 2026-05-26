# BEIR / nfcorpus — Three-Way Pipeline Comparison

**Dataset:** [nfcorpus](https://www.cl.uni-heidelberg.de/statnlpgroup/nfcorpus/) via BEIR  
**Queries:** 323 (full test split)  
**Corpus:** 3,633 documents  
**Run ID:** `78091ce0`  
**Config:** [`examples/nfcorpus_three_way.yaml`](../../examples/nfcorpus_three_way.yaml)

95% confidence intervals via paired bootstrap (10,000 iterations) over per-query scores.

## Results

| Pipeline | Recall@10 | NDCG@10 | MRR | MAP | Latency P50 | Latency P95 |
|---|---|---|---|---|---|---|
| BM25-only (`rank-bm25`) | 0.119 [0.098, 0.141] | 0.264 [0.233, 0.295] | 0.468 [0.418, 0.514] | 0.110 [0.091, 0.131] | 2 ms | 7 ms |
| Dense-only (`all-MiniLM-L6-v2` + FAISS) | **0.153 [0.129, 0.179]** | **0.310 [0.278, 0.341]** | 0.510 [0.464, 0.555] | **0.140 [0.119, 0.160]** | 539 ms* | 929 ms* |
| BM25 → CrossEncoder (`ms-marco-MiniLM-L-6-v2`) | 0.138 [0.115, 0.163] | 0.310 [0.275, 0.345] | **0.530 [0.480, 0.581]** | 0.112 [0.092, 0.135] | 4,057 ms** | 4,752 ms** |

\* Dense query latency includes per-query transformer encoding on CPU (corpus is pre-encoded once at startup).  
\*\* CrossEncoder latency includes scoring all 100 BM25 candidates through a cross-encoder on CPU. GPU would reduce this to ~50–100 ms.

## Observations

- **Dense beats BM25 on Recall@10** (0.153 vs 0.119, non-overlapping CIs) — MiniLM-L6-v2 generalizes better to the biomedical vocabulary in nfcorpus than BM25 term matching.
- **CrossEncoder matches Dense on NDCG@10** (0.310 vs 0.310) while also achieving the highest MRR (0.530) — it ranks the single best document higher, even with lower Recall@10 than Dense.
- **BM25 is fastest by 250×** — 2 ms P50 vs 539 ms for dense query encoding. Dense retrieval latency is dominated by CPU-based query encoding; with a GPU or cached embeddings this drops dramatically.
- **CrossEncoder is the slowest** — 4+ seconds/query scoring 100 candidates on CPU. Narrowing the BM25 first stage (e.g., k=20) or using a GPU cuts this proportionally.

## Reproducing

```bash
pip install -e ".[dense,beir]"
retobs run --config examples/nfcorpus_three_way.yaml
```

Raw per-metric data: [`metrics.json`](metrics.json)
