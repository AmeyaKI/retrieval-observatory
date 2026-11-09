# Examples

Choose an example by the task you need to verify. For the whole loop on deterministic data, run
`retobs demo` first (see [getting started](../docs/guides/getting-started.md)). Experiment configs
(YAML) run with `retobs evaluate --config <file>`.

## Evaluate

- [basic/evaluate_callable.py](basic/evaluate_callable.py) — evaluate a Python callable, single- and multi-stage.
- [basic/evaluate_toy.py](basic/evaluate_toy.py) — the lower-level runner, store, and metrics engine on the test fixtures.
- [basic/evaluate_scifact.yaml](basic/evaluate_scifact.yaml) — BM25 on 50 SciFact queries.
- [basic/beir_demo.yaml](basic/beir_demo.yaml) and [basic/beir_demo.py](basic/beir_demo.py) — BM25 baseline on the full NFCorpus test split.
- [advanced/custom_retriever](advanced/custom_retriever) — a Python retriever loaded through `adapter.import`.
- [advanced/temporal_demo](advanced/temporal_demo) — standard recall against temporal recall on a small timestamped corpus.
- [advanced/hybrid_fiqa_demo](advanced/hybrid_fiqa_demo) — hybrid DAG on BEIR datasets (downloads an embedding model).

## Benchmark configs

- [benchmarks/three_stage_cascade.yaml](benchmarks/three_stage_cascade.yaml) — BM25 with two cross-encoder rerank stages and their ablations.
- [benchmarks/nfcorpus_rag_pipeline.yaml](benchmarks/nfcorpus_rag_pipeline.yaml) — BM25 against BM25 with a cross-encoder reranker.
- [benchmarks/nfcorpus_bm25_vs_minilm.yaml](benchmarks/nfcorpus_bm25_vs_minilm.yaml) — BM25 against a MiniLM bi-encoder.
- [benchmarks/nfcorpus_three_way.yaml](benchmarks/nfcorpus_three_way.yaml) — BM25, dense, and BM25 with a cross-encoder.
- [benchmarks/rrf_hybrid.yaml](benchmarks/rrf_hybrid.yaml) — BM25, dense, and their reciprocal rank fusion.
- [benchmarks/cohere_reranker.yaml](benchmarks/cohere_reranker.yaml) and [benchmarks/hybrid_comparison.yaml](benchmarks/hybrid_comparison.yaml) — Cohere reranking (needs `COHERE_API_KEY`).
- [benchmarks/temporal_eval.yaml](benchmarks/temporal_eval.yaml) — template for temporal recall against HTTP retrieval and rerank endpoints you supply.
- [beir_publish](beir_publish) — smoke and cascade configs for the published BEIR results.

## Connect

Plain Python first, then the framework adapters:

- [integrations/manual_class_pipeline](integrations/manual_class_pipeline) — `@observe` and `@trace_scope` on a class-based, multi-module pipeline ([guide](../docs/guides/manual-instrumentation.md)).
- [integrations/fastapi_search](integrations/fastapi_search) — FastAPI instrumentation.
- [integrations/langchain_search](integrations/langchain_search) — LangChain retriever callback.
- [integrations/llamaindex_search](integrations/llamaindex_search) — LlamaIndex retriever callback.
- [integrations/haystack_search](integrations/haystack_search) — Haystack component wrapper.
- [integrations/dspy_search](integrations/dspy_search) — DSPy retrieval wrapper.
- [integrations/openai_agents_search](integrations/openai_agents_search) — OpenAI Agents SDK retrieval tool wrapper.
- [integrations/http_evaluation](integrations/http_evaluation) — evaluate an HTTP endpoint (final output only).
- [integrations/mcp_agent.yaml](integrations/mcp_agent.yaml) — MCP client configuration.

## Audit

- [ci/retrieval-ci.yml](ci/retrieval-ci.yml) — GitHub Actions release gate with exit codes.
- [ci/release-policy-v3.yaml](ci/release-policy-v3.yaml) — v3 release policy with semantic selectors.
- [ci/release-policy.yaml](ci/release-policy.yaml) — schema 2 release policy with positional stage keys.

## Pipeline patterns

- [advanced/self_correcting_rag_demo](advanced/self_correcting_rag_demo) — conditional retrieve, critique, retry.

All examples are local demonstrations. An integration becomes ready only after plan, apply, and
observed verification evidence are present.
