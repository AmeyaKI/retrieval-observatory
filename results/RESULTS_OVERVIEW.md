# Benchmark results index (v0.1.2)

Full analysis: **[results/BENCHMARK_ANALYSIS.md](BENCHMARK_ANALYSIS.md)**

## Run registry


| Dataset                   | SQLite (local)                       | Run ID     | Export folder                        |
| ------------------------- | ------------------------------------ | ---------- | ------------------------------------ |
| NFCorpus sweep            | `.retobs/publish_sweep_nfcorpus.db`  | `37d3a79c` | [nfcorpus/](nfcorpus/)               |
| SciFact sweep             | `.retobs/publish_sweep_scifact.db`   | `49b423cf` | [scifact/](scifact/)                 |
| FiQA sweep                | `.retobs/publish_sweep_fiqa.db`      | `0784ed30` | [fiqa/](fiqa/)                       |
| NFCorpus Cohere (partial) | `.retobs/publish_cohere_nfcorpus.db` | `a6dad22f` | [cohere_nfcorpus/](cohere_nfcorpus/) |


SQLite databases are gitignored. JSON exports in each folder are committed for reproducibility without re-running sweeps.

## Artifacts per dataset


| File                       | Contents                                                     |
| -------------------------- | ------------------------------------------------------------ |
| `metrics.json`             | Aggregated per-pipeline metrics (NDCG, Recall, MRR, latency) |
| `diagnostics.json`         | Failure labels and difficulty bucket aggregates              |
| `stage_contributions.json` | Stage attribution deltas (bm25 → bm25__rerank)               |
| `run_meta.json`            | Run ID, experiment name, DB path                             |


Cross-dataset aggregate: [analytics_extract.json](analytics_extract.json)

## Regenerating results

From a local SQLite DB (requires running the sweep first):

```bash
# Export per-dataset JSON
python scripts/export_results.py \
  --db .retobs/publish_sweep_nfcorpus.db \
  --run-id 37d3a79c \
  --out-dir results/nfcorpus

# Recompute analytics extract (all publish DBs must exist locally)
python scripts/bench_analytics.py > results/analytics_extract.json

# Regenerate dashboard screenshots
python scripts/generate_dashboard_screenshots.py
```

Reproduce full sweep from configs:

```bash
pip install -e ".[demo,dashboard,dense]"
./scripts/run_beir_publish.sh full-sweep
```

Configs: [configs/beir_publish/](../configs/beir_publish/)

## Screenshots and release checklist

Dashboard visualizations for the README and [BENCHMARK_ANALYSIS.md](BENCHMARK_ANALYSIS.md): [screenshots/](screenshots/)

Pre-release spot-check: [dashboard_audit.md](dashboard_audit.md)