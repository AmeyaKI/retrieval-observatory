# Migration and deprecations

The task-oriented names shipped before legacy removal. Existing databases and V1/V2 compatibility readers remain supported during the deprecation window.

| Legacy surface | Replacement | Removal target |
|---|---|---|
| `retobs run --config FILE` | `retobs evaluate --config FILE` | v1.0 |
| `retobs wire` | `retobs integrate` | v1.0 |
| `retobs forge ...` | `retobs testsets ...` | v1.0 |
| `retobs tracelens ...` | `retobs production ...` | v1.0 |
| `retobs advisor check` | `retobs compare BASELINE CANDIDATE --fail-on regression` | v1.0 |
| `retobs inspect RUN --query QUERY` | `retobs inspect-query RUN QUERY` | v1.0 |
| MCP `benchmark_config` | MCP `evaluate` | v1.0 |
| MCP `benchmark_config_file` | MCP `evaluate_file` | v1.0 |

Legacy CLI groups are hidden from top-level help but still callable and print the exact replacement. Low-level SDK modules remain available where they represent real engine concepts. Old stored Test Set summaries/manifests/traces are migrated on read; removal of a command does not rewrite or corrupt stored data.
