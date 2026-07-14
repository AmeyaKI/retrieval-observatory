# Usage

The public workflow is organized by task:

1. [Start with a callable](START.md).
2. Follow the [baseline-to-validation workflow](WORKFLOW.md).
3. Use the [CLI/SDK/MCP task reference](REFERENCE.md).
4. Read [evidence and trust semantics](EVIDENCE_AND_TRUST.md) before interpreting comparisons or replay.
5. Use the [advanced YAML guide](YAML_GUIDE.md) only when callable-first evaluation is insufficient.

Primary commands:

```bash
retobs evaluate module:symbol
retobs compare BASELINE CANDIDATE
retobs inspect-query RUN QUERY
retobs report RUN --format json
retobs integrate . --plan
retobs verify
retobs serve
```

Production tracing and corpus-derived generation are available under `retobs production` and `retobs testsets`. Historical Forge, TraceLens, Advisor, and Benchmarks terminology refers to internal engines or deprecated aliases; see [Migration](MIGRATION.md).
