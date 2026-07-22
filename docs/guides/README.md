# retobs Guides

Start here:

- **[getting-started.md](getting-started.md)** — the beginner journey: install → run →
  debug a failure → improve → validate, in under an hour.

Advanced topics — each pairs the retrieval-engineering concept with how retobs visualizes and
diagnoses it:

- [hybrid-retrieval.md](hybrid-retrieval.md) — combining lexical and dense arms
- [parallel-retrieval.md](parallel-retrieval.md) — multiple lanes, fused
- [multi-stage-reranking.md](multi-stage-reranking.md) — precision without losing recall
- [conditional-pipelines.md](conditional-pipelines.md) — gates, routing, skipped branches
- [counterfactual-replay.md](counterfactual-replay.md) — how attribution actually works
- [forge.md](forge.md) — corpus-specific stress tests
- [tracelens.md](tracelens.md) — observing production retrieval
- [advisor.md](advisor.md) — from diagnostics to a prioritized plan
- [auto-instrumentation.md](auto-instrumentation.md) — tracing without per-call-site code (LangChain proof of concept)
- [retrieval-release-decisions.md](retrieval-release-decisions.md) — bounded local/CI promotion evidence
- [candidate-lineage-explorer.md](candidate-lineage-explorer.md) — static recorded paths, outcomes, passports, and safe diffs

For the full CLI/config reference see [../USAGE.md](../USAGE.md) and
[../YAML_GUIDE.md](../YAML_GUIDE.md).

For the current task-oriented entry points, start with [Start](../START.md), [Workflow](../WORKFLOW.md), and [Reference](../REFERENCE.md). Guides that retain Test Sets, Production, or Findings in their filename describe the corresponding Test Sets, Production, or embedded Findings engine; those names are no longer peer products in navigation.
