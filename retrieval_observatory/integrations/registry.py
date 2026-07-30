from __future__ import annotations

from typing import Any, Dict, List, Optional

# Single source for agent-facing integration guidance (MCP describe_integration + docs build).

INTEGRATION_GUIDES: Dict[str, Dict[str, Any]] = {
    "python": {
        "title": "Python callable, adapter.import factory, or @observe tracing",
        "install_extra": None,
        "env_vars": [],
        "snippet": (
            "# Option A — SDK benchmark (no YAML):\n"
            "import retrieval_observatory as ro\n\n"
            "def retrieve(q: str) -> list[str]:\n"
            "    return my_index.search(q, k=100)\n\n"
            "report = ro.benchmark(retrieve, queries=queries, corpus=corpus, k=10)\n"
            "report.show()\n\n"
            "# Option B — YAML adapter.import (factory next to config.yaml):\n"
            "# stages: [{type: adapter.import, retriever_id: my_retriever,\n"
            "#           config: {factory: retriever.build_retriever, k: 10}}]\n"
            "# Run: retobs evaluate --config retobs/config.yaml\n"
            "# Or MCP: evaluate_file(config_path='.../retobs/config.yaml')\n\n"
            "# Option C — production tracing (V2 operator DAG):\n"
            "from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n\n"
            "@observe(op_type='SOURCE', op_id='my_retriever')\n"
            "def retrieve(query: str): ...\n\n"
            "start_trace(ObserveContext(run_id='run-1', query_id='q1', query_text=query, pipeline_id='main'))\n"
            "retrieve(query)\n"
            "trace = finish_trace()\n"
            "# Push: MCP push_traces(run_id='run-1', traces=[trace.to_dict()])"
        ),
        "verify": "Benchmark: run a 5-query smoke test; expect metrics with pipeline_id set. Tracing: verify_integration with trace_count > 0.",
    },
    "langchain": {
        "title": "LangChain retriever callback",
        "install_extra": "langchain",
        "env_vars": [],
        "snippet": (
            "import retrieval_observatory as ro\n"
            "from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback\n"
            "from retrieval_observatory.tracing.integrations.operator_registry import OperatorRegistry\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n"
            "registry = OperatorRegistry.explicit(component_path='retriever', op_id='retrieve', op_type='SOURCE')\n"
            "cb = RetobsLangChainCallback(recorder, registry)\n"
            "docs = retriever.invoke(query, config={'callbacks': [cb]})\n"
            "# Push traces: MCP push_traces(run_id=..., traces=[...]) or REST POST /dbs/{id}/runs/{run_id}/traces"
        ),
        "verify": "After 1+ traced queries, call verify_integration — expect stages_seen from callback spans.",
    },
    "llamaindex": {
        "title": "LlamaIndex query instrumentation",
        "install_extra": "llamaindex",
        "env_vars": [],
        "snippet": (
            "import retrieval_observatory as ro\n"
            "from llama_index.core.callbacks import CallbackManager\n"
            "from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexCallback\n"
            "from retrieval_observatory.tracing.integrations.operator_registry import OperatorRegistry\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n"
            "registry = OperatorRegistry.explicit(component_path='retrieve', op_id='retrieve', op_type='SOURCE')\n"
            "handler = RetobsLlamaIndexCallback(recorder, registry)\n"
            "engine = index.as_query_engine(callback_manager=CallbackManager([handler]))\n"
            "engine.query(q)"
        ),
        "verify": "After 1+ traced queries, call verify_integration — expect operator spans in the run.",
    },
    "fastapi": {
        "title": "FastAPI search service (HTTP adapter or middleware)",
        "install_extra": "fastapi",
        "env_vars": ["RETOBS_API_TOKEN (optional, for remote push)"],
        "snippet": (
            "# Option A — benchmark existing HTTP endpoint (no code change):\n"
            "# stages: [{type: adapter.http, url: http://localhost:8000/search, ...}]\n\n"
            "# Option B — trace in-process (see examples/integrations/fastapi_search/app.py):\n"
            "import retrieval_observatory as ro\n"
            "from retrieval_observatory.tracing.integrations.fastapi import get_trace, instrument_fastapi\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n"
            "instrument_fastapi(app, recorder, pipeline_id='main')\n\n"
            "@app.get('/search')\n"
            "async def search(q: str, request: Request):\n"
            "    t = get_trace(request)\n"
            "    docs = my_retriever.search(q)\n"
            "    t.stage('bm25', docs, latency_ms=...)\n"
            "    return docs"
        ),
        "verify": "HTTP adapter: benchmark_config with adapter.http. In-process: verify_integration after traces.",
    },
    "haystack": {
        "title": "Haystack pipeline component tracing",
        "install_extra": "haystack",
        "env_vars": [],
        "snippet": (
            "import retrieval_observatory as ro\n"
            "from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace\n"
            "from retrieval_observatory.tracing.integrations.haystack import wrap_haystack_component\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n\n"
            "# Wrap each retrieval/rerank component once, in place -- no per-call code needed after this:\n"
            "wrap_haystack_component(retriever, op_type='SOURCE', op_id='bm25')\n"
            "wrap_haystack_component(ranker, op_type='RERANK', op_id='ranker')\n\n"
            "start_trace(ObserveContext(run_id='run-1', query_id='q1', query_text=query, pipeline_id='main'))\n"
            "result = pipeline.run({'retriever': {'query': query}})\n"
            "trace = finish_trace()\n"
            "# Push: MCP push_traces(run_id='run-1', traces=[trace.to_dict()])"
        ),
        "verify": "After 1+ traced queries, call verify_integration — expect a span per wrapped Haystack component.",
    },
    "dspy": {
        "title": "DSPy retrieval module tracing",
        "install_extra": "dspy",
        "env_vars": [],
        "snippet": (
            "import dspy\n"
            "import retrieval_observatory as ro\n"
            "from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace\n"
            "from retrieval_observatory.tracing.integrations.dspy import wrap_retrieve\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n"
            "retrieve = wrap_retrieve(dspy.Retrieve(k=20), op_id='dspy_retrieve')\n\n"
            "start_trace(ObserveContext(run_id='run-1', query_id='q1', query_text=query, pipeline_id='main'))\n"
            "retrieve(query)\n"
            "trace = finish_trace()\n"
            "# Push: MCP push_traces(run_id='run-1', traces=[trace.to_dict()])"
        ),
        "verify": "After 1+ traced queries, call verify_integration — expect the dspy_retrieve SOURCE span.",
    },
    "openai_agents": {
        "title": "OpenAI Agents SDK retrieval-tool tracing",
        "install_extra": "openai-agents",
        "env_vars": ["OPENAI_API_KEY"],
        "snippet": (
            "from agents import function_tool\n"
            "import retrieval_observatory as ro\n"
            "from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace\n"
            "from retrieval_observatory.tracing.integrations.openai_agents import wrap_retrieval_tool\n\n"
            "recorder = ro.init(service='my-rag', db='.retobs/prod.db')\n\n"
            "def kb_search(query: str) -> list[dict]:\n"
            "    return my_index.search(query, k=20)\n\n"
            "kb_search_tool = function_tool(wrap_retrieval_tool(kb_search, op_id='kb_search'))\n\n"
            "start_trace(ObserveContext(run_id='run-1', query_id='q1', query_text=query, pipeline_id='main'))\n"
            "# ... run the agent; its retrieval tool call is traced ...\n"
            "trace = finish_trace()\n"
            "# Push: MCP push_traces(run_id='run-1', traces=[trace.to_dict()])"
        ),
        "verify": "After 1+ agent runs that hit the retrieval tool, call verify_integration — expect the kb_search span.",
    },
    "http": {
        "title": "Remote HTTP retrieval endpoint (read-only benchmark)",
        "install_extra": None,
        "env_vars": [],
        "snippet": (
            "pipelines:\n"
            "  - id: my_service\n"
            "    stages:\n"
            "      - type: adapter.http\n"
            "        url: http://your-service/retrieve\n"
            "        retriever_id: my_service\n"
            "        config: {id_field: id, text_field: text, score_field: score, k: 10}"
        ),
        "verify": "validate_config then benchmark_config with max_queries=10; expect run_id + metrics.",
    },
}

SUPPORT_LEVELS: Dict[str, Dict[str, Any]] = {
    "python": {"level": "first_class", "kind": "framework", "owner": "retobs-core"},
    "http": {"level": "first_class", "kind": "framework", "owner": "retobs-core"},
    "fastapi": {"level": "first_class", "kind": "framework", "owner": "retobs-core"},
    "langchain": {"level": "first_class", "kind": "framework", "owner": "retobs-core"},
    "llamaindex": {"level": "first_class", "kind": "framework", "owner": "retobs-core"},
    "haystack": {"level": "supported_example", "kind": "framework", "owner": "community"},
    "dspy": {"level": "supported_example", "kind": "framework", "owner": "community"},
    "openai_agents": {"level": "supported_example", "kind": "framework", "owner": "community"},
    "pgvector": {"level": "first_class", "kind": "data_adapter", "owner": "retobs-core"},
    "qdrant": {"level": "first_class", "kind": "data_adapter", "owner": "retobs-core"},
    "hybrid_rerank": {"level": "architecture_recipe", "kind": "recipe", "owner": "retobs-core"},
}


def list_integration_frameworks() -> List[str]:
    return sorted(INTEGRATION_GUIDES.keys())


def describe_integration(framework: Optional[str] = None) -> Dict[str, Any]:
    if framework is None:
        return {
            "frameworks": list_integration_frameworks(),
            "guides": INTEGRATION_GUIDES,
            "support_levels": SUPPORT_LEVELS,
            "next": "Call describe_integration(framework='...') for one path, then verify_integration after wiring.",
        }
    key = framework.lower().strip()
    if key not in INTEGRATION_GUIDES:
        return {
            "error": f"Unknown framework '{framework}'",
            "frameworks": list_integration_frameworks(),
        }
    guide = dict(INTEGRATION_GUIDES[key])
    guide["framework"] = key
    guide["support"] = SUPPORT_LEVELS[key]
    guide["next"] = "Wire the snippet, run one query, then call verify_integration."
    return guide
