# retobs Guides

Start here:

- **[getting-started.md](getting-started.md)** — the beginner journey: install → run →
  debug a failure → improve → validate, in under an hour.

Production guides — each pairs the retrieval-engineering concept with how retobs diagnoses it:

- [hybrid-retrieval.md](hybrid-retrieval.md) — combining lexical and dense arms
- [counterfactual-replay.md](counterfactual-replay.md) — how attribution actually works
- [candidate-lineage-explorer.md](candidate-lineage-explorer.md) — static recorded paths, outcomes, passports, and safe diffs
- [retrieval-release-decisions.md](retrieval-release-decisions.md) — bounded local/CI promotion evidence
- [tracelens.md](tracelens.md) — observing production retrieval

Experimental guides live in [experimental/](experimental/). They describe subsystems under
`retrieval_observatory.experimental` (advisor, forge, auto-instrumentation) and pipeline
patterns whose guides have not been re-verified against the current build. No compatibility
guarantee.

For the full CLI/config reference see [../USAGE.md](../USAGE.md) and
[../YAML_GUIDE.md](../YAML_GUIDE.md).

For the current task-oriented entry points, start with [Start](../START.md), [Workflow](../WORKFLOW.md), and [Reference](../REFERENCE.md). Guides that retain Test Sets, Production, or Findings in their filename describe the corresponding Test Sets, Production, or embedded Findings engine; those names are no longer peer products in navigation.
