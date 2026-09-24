# Experimental and retired guides

## Retired in 0.7.0

These subsystems were removed from the package in 0.7.0. They are absent from the 0.7.0 wheel,
CLI, SDK, MCP server, and dashboard, and nothing replaces them unless a replacement is named.

| Removed | What it was | Replacement |
|---|---|---|
| `retrieval_observatory/experimental/forge/`, SDK `TestSet` and `generate_testset`, `retobs testsets scan\|generate\|list` | Synthetic test-set generation and stress suites | None. Evaluate against a prepared benchmark (JSONL queries/corpus/qrels or BEIR) with `retobs evaluate` |
| `retrieval_observatory/experimental/classifier/`, the `classifier` extra (`scikit-learn`, `joblib`) | Learned pre-retrieval query difficulty | None |
| `retrieval_observatory/experimental/advisor/` | Recommendations, regression detection, reliability snapshots | `retobs compare --policy` for release decisions; `retobs inspect-query` / `inspect-document` for loss evidence |
| `retrieval_observatory/experimental/diagram/` | Static HTML pipeline diagram | The dashboard pipeline view |
| `retobs production demo\|stats\|purge`, `tracing/enrich.py` | Synthetic production traces and label-free trace enrichment | None |
| The pre-0.6.0 import aliases `retrieval_observatory.{advisor,classifier,diagram,forge}` | Deprecated module shims | None |

`retobs demo` now evaluates two deterministic runs of the golden hybrid fixture (no models or
network) instead of the synthetic test-set story.

Databases written by earlier versions stay readable: the `forge_*`, `reliability_snapshots`, and
`query_diagnostics` tables are kept as historical data. Published results are not regenerated.

To reproduce anything that used these subsystems, pin the last release that shipped them:

```bash
pip install retrieval-observatory==0.6.0
# or, from a clone of the repository
git checkout 29c67b8
```

[advisor.md](advisor.md) and [forge.md](forge.md) describe the retired subsystems as they were in 0.6.0.

## Pipeline-pattern guides

These guides describe retained pipeline patterns but have not been re-verified against the
current build:

- [auto-instrumentation.md](auto-instrumentation.md)
- [conditional-pipelines.md](conditional-pipelines.md)
- [multi-stage-reranking.md](multi-stage-reranking.md)
- [parallel-retrieval.md](parallel-retrieval.md)
