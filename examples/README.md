# Examples

Choose an example by the task you need to verify. For the whole loop on deterministic data, run
`retobs demo` first (see [getting started](../docs/guides/getting-started.md)).

## Evaluate

- [basic/evaluate_callable.py](basic/evaluate_callable.py) — evaluate a Python callable.
- [basic/evaluate_toy.py](basic/evaluate_toy.py) — small local evaluation.
- [basic/evaluate_scifact.yaml](basic/evaluate_scifact.yaml) — SciFact YAML evaluation.
- [benchmarks/three_stage_cascade.yaml](benchmarks/three_stage_cascade.yaml) — multi-stage configuration.
- [advanced/hybrid_fiqa_demo](advanced/hybrid_fiqa_demo) — hybrid DAG on BEIR datasets (downloads an embedding model).

## Connect

Plain Python first, then the framework adapters:

- [integrations/manual_class_pipeline](integrations/manual_class_pipeline) — `@observe` and `@trace_scope` on a class-based, multi-module pipeline ([guide](../docs/guides/manual-instrumentation.md)).
- [integrations/fastapi_search](integrations/fastapi_search) — FastAPI instrumentation.
- [integrations/langchain_search](integrations/langchain_search) — LangChain retriever.
- [integrations/llamaindex_search](integrations/llamaindex_search) — LlamaIndex retriever.
- [integrations/http_evaluation](integrations/http_evaluation) — evaluate an HTTP endpoint (final output only).
- [integrations/mcp_agent.yaml](integrations/mcp_agent.yaml) — MCP client configuration.

## Audit

- [ci/retrieval-ci.yml](ci/retrieval-ci.yml) — GitHub Actions release gate with exit codes.
- [ci/release-policy-v3.yaml](ci/release-policy-v3.yaml) — v3 release policy with semantic selectors.

## Pipeline patterns

- [advanced/self_correcting_rag_demo](advanced/self_correcting_rag_demo) — conditional retrieve, critique, retry.
- [advanced/complex_rag_demo](advanced/complex_rag_demo) — gated multi-source pipeline with all operator types. Not runnable on the current trace API (it calls a removed `TraceContext.add_span`); kept for reference until it is ported.

All examples are local demonstrations. An integration becomes ready only after plan, apply, and observed verification evidence are present.
