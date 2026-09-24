# retobs guides

Start here:

- **[getting-started.md](getting-started.md)**: the demo end to end, then your own pipeline.
- **[investigate-your-pipeline.md](investigate-your-pipeline.md)**: from a Run to a query's
  candidates to one document's journey and loss boundary.
- **[retrieval-release-decisions.md](retrieval-release-decisions.md)**: audit a baseline against a
  candidate under a v3 policy, locally and in CI.
- **[evidence-limitations.md](evidence-limitations.md)**: judgments and units, unjudged documents,
  partial capture, skipped branches, and what an audit does and does not certify.
- **[migrating-to-focused-retobs.md](migrating-to-focused-retobs.md)**: what 0.7.0 removed and what
  replaces it.

Pipeline guides:

- [manual-instrumentation.md](manual-instrumentation.md): hand-wiring a class-based, multi-module
  pipeline into one trace when `retobs integrate` cannot see the whole DAG.
- [hybrid-retrieval.md](hybrid-retrieval.md): lexical and dense lanes, fused.
- [experimental/](experimental/README.md): pipeline-pattern guides (reranking, parallel lanes,
  gates, auto-instrumentation) and the subsystems retired in 0.7.0 with the pinned release that
  reproduces them.

Retired pages kept so old links resolve: [candidate-lineage-explorer.md](candidate-lineage-explorer.md)
(now Investigate), [counterfactual-replay.md](counterfactual-replay.md), and
[tracelens.md](tracelens.md).

For the CLI, SDK, and MCP reference see [../REFERENCE.md](../REFERENCE.md); for advanced YAML
pipelines see [../YAML_GUIDE.md](../YAML_GUIDE.md).
