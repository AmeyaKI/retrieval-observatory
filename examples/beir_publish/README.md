# BEIR publish benchmarks

Configs for GitHub-published results. See repo root plan / `scripts/run_beir_publish.sh`.

| Config | Queries | Pipelines |
|--------|---------|-----------|
| `smoke_*.yaml` | 20 | 4 (sweep) or 2 (cohere) |
| `sweep_*.yaml` | full test split | 4 |
| `cohere_nfcorpus.yaml` | full | 2 |
| `cascade_nfcorpus.yaml` | full (or 100 for trial) | 4 |

**Sweep pipelines:** `bm25`, `dense_only`, `rrf_hybrid`, `bm25__rerank`
