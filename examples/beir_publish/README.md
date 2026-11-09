# BEIR publish benchmarks

Configs behind the published BEIR results in [results/](../../results/RESULTS_OVERVIEW.md).
[`scripts/run_beir_publish.sh`](../../scripts/run_beir_publish.sh) runs each config with
`retobs evaluate --config`. The full-sweep and full Cohere configs live in
[configs/beir_publish/](../../configs/beir_publish/); this directory holds the smoke configs and
the cascade config.

| Config | Queries | Pipelines | Script target |
|--------|---------|-----------|---------------|
| `smoke_nfcorpus.yaml`, `smoke_scifact.yaml`, `smoke_fiqa.yaml` | 20 | 4 (sweep) | `smoke-sweep` |
| `smoke_cohere_nfcorpus.yaml` | 20 | 2 | `smoke-cohere` (needs `COHERE_API_KEY`) |
| `smoke_cascade_nfcorpus.yaml` | 20 | 4 | `smoke-cascade` |
| `cascade_nfcorpus.yaml` | full test split | 4 | `cascade-nfcorpus` |
| `../../configs/beir_publish/sweep_*.yaml` | full test split | 4 | `full-sweep` |
| `../../configs/beir_publish/cohere_nfcorpus.yaml` | full | 2 | `cohere-nfcorpus` (needs `COHERE_API_KEY`) |

`smoke` runs every smoke config, including the Cohere one.

**Sweep pipelines:** `bm25`, `dense_only`, `rrf_hybrid`, `bm25__rerank`.
