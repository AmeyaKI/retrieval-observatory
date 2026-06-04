# NFCorpus export artifacts

Part of the BEIR publish sweep (run `37d3a79c`, 323 queries, 4 pipelines).

Full cross-dataset analysis: [BENCHMARK_ANALYSIS.md](../BENCHMARK_ANALYSIS.md)

## Files

| File | Description |
| ---- | ----------- |
| [metrics.json](metrics.json) | Aggregated NDCG@10, Recall@10, MRR, latency per pipeline |
| [diagnostics.json](diagnostics.json) | Failure labels and difficulty bucket counts |
| [stage_contributions.json](stage_contributions.json) | bm25 → bm25__rerank stage attribution deltas |
| [run_meta.json](run_meta.json) | Run ID and DB path reference |

Config: [configs/beir_publish/sweep_nfcorpus.yaml](../../configs/beir_publish/sweep_nfcorpus.yaml)
