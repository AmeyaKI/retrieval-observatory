# Architecture

retobs has one evidence spine:

```text
callable/config/instrumentation
        -> executor + V2 operator traces
        -> Run manifest + scoped store
        -> metrics/diagnostics/comparison
        -> Run report + QueryEvidence + PipelineGraphV2
        -> CLI / SDK / MCP / API / dashboard
```

The executor records wall-clock, critical-path, operator-sum, fired/skipped, cache, timeout, cancellation, partial output, parents, and candidate transitions. SQLite and PostgreSQL implement the same store protocol and contract suite. API evidence reads always select a database before a Run/query.

The dashboard consumes canonical backend projections instead of independently inferring topology or causality. Aggregate graph views use the union of observed real edges; exact views select one trace. Reports are renderer-neutral models shared by terminal, JSON, Markdown, and standalone HTML.

Internal packages retain historical names (`forge`, `tracelens`, `advisor`) for compatibility, but public tasks are Evaluate, Compare, Queries, Production, and Test Sets.
