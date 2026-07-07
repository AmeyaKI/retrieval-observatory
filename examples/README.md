# Examples cheat sheet

This folder is organized by use case so you can quickly choose the right starting point.

## Quick picks

- Want the simplest SDK walkthrough? Start with [basic/sdk_quickstart.py](basic/sdk_quickstart.py).
- Want a tiny local benchmark with no external dependencies? Start with [basic/quickstart.py](basic/quickstart.py).
- Want a realistic BEIR-style benchmark? Start with [benchmarks/three_stage_cascade.yaml](benchmarks/three_stage_cascade.yaml) or [benchmarks/rrf_hybrid.yaml](benchmarks/rrf_hybrid.yaml).
- Want tracing or instrumentation for an existing service? Start with [integrations/fastapi_search](integrations/fastapi_search), [integrations/langchain_search](integrations/langchain_search), or [integrations/llamaindex_search](integrations/llamaindex_search).
- Want the most advanced DAG-style or custom-pipeline demo? Start with [advanced/complex_rag_demo](advanced/complex_rag_demo).

## Folder map

### basic/
Use these for the smallest, easiest entry points.

- [basic/quickstart.py](basic/quickstart.py) — toy benchmark with a mock retriever.
- [basic/sdk_quickstart.py](basic/sdk_quickstart.py) — wrap your own retriever and benchmark it in pure Python.
- [basic/demo_phases.py](basic/demo_phases.py) — guided walkthrough of SDK phases.
- [basic/beir_demo.py](basic/beir_demo.py) and [basic/beir_demo.yaml](basic/beir_demo.yaml) — BM25 baseline on NFCorpus.
- [basic/quickstart_scifact.yaml](basic/quickstart_scifact.yaml) — minimal YAML benchmark example.

Run:

```bash
python examples/basic/sdk_quickstart.py
python examples/basic/beir_demo.py
```

### benchmarks/
Use these when you want to compare retrieval architectures or evaluate retrieval quality on public datasets.

- [benchmarks/three_stage_cascade.yaml](benchmarks/three_stage_cascade.yaml) — three-stage cascade reranker analysis.
- [benchmarks/rrf_hybrid.yaml](benchmarks/rrf_hybrid.yaml) — BM25 + dense hybrid via reciprocal rank fusion.
- [benchmarks/hybrid_comparison.yaml](benchmarks/hybrid_comparison.yaml) — dense-only vs BM25 + Cohere rerank.
- [benchmarks/cohere_reranker.yaml](benchmarks/cohere_reranker.yaml) — simpler Cohere rerank demo.
- [benchmarks/temporal_eval.yaml](benchmarks/temporal_eval.yaml) — temporal-aware evaluation pattern.
- [benchmarks/nfcorpus_bm25_vs_minilm.yaml](benchmarks/nfcorpus_bm25_vs_minilm.yaml) — BM25 vs MiniLM comparison.
- [benchmarks/nfcorpus_rag_pipeline.yaml](benchmarks/nfcorpus_rag_pipeline.yaml) — RAG-style benchmark config.
- [benchmarks/nfcorpus_three_way.yaml](benchmarks/nfcorpus_three_way.yaml) — three-way retrieval comparison.

Run:

```bash
retobs run --config examples/benchmarks/three_stage_cascade.yaml
retobs run --config examples/benchmarks/rrf_hybrid.yaml
```

### integrations/
Use these when you want to instrument an existing app or service.

- [integrations/fastapi_search](integrations/fastapi_search) — FastAPI demo with tracing.
- [integrations/langchain_search](integrations/langchain_search) — LangChain callback-based tracing.
- [integrations/llamaindex_search](integrations/llamaindex_search) — LlamaIndex callback-based tracing.
- [integrations/http_quickstart](integrations/http_quickstart) — benchmark a live HTTP retrieval endpoint.
- [integrations/mcp_agent_quickstart.yaml](integrations/mcp_agent_quickstart.yaml) — MCP agent quickstart config.

Run:

```bash
python examples/integrations/fastapi_search/app.py
python examples/integrations/langchain_search/app.py
python examples/integrations/llamaindex_search/app.py
```

### tracing/
Use these for tracing-specific examples.

- [tracing/langchain_tracing](tracing/langchain_tracing)
- [tracing/llamaindex_tracing](tracing/llamaindex_tracing)

### advanced/
Use these when you want richer, more realistic multi-stage or custom-pipeline behavior.

- [advanced/complex_rag_demo](advanced/complex_rag_demo) — full trace-native operator DAG demo.
- [advanced/custom_retriever](advanced/custom_retriever) — custom Python retriever via adapter import.
- [advanced/self_correcting_rag_demo](advanced/self_correcting_rag_demo) — retrieve → critique → retry topology.
- [advanced/temporal_demo](advanced/temporal_demo) — temporal retrieval demo.
- [advanced/dashboard_demo](advanced/dashboard_demo) — benchmark → train classifier → dashboard workflow.
- [advanced/hybrid_fiqa_demo](advanced/hybrid_fiqa_demo) — hybrid BEIR demo with real datasets.

Run:

```bash
python examples/advanced/complex_rag_demo/run_demo.py
retobs serve --db .retobs/complex_rag_demo.db
```

### ci/
Use this for CI regression gating examples.

- [ci/retrieval-ci.yml](ci/retrieval-ci.yml)

### beir_publish/
Use these for published BEIR-style benchmark configs.

- [beir_publish/README.md](beir_publish/README.md)
