from __future__ import annotations

from typing import Any, Dict, List, Optional

# Single source for agent-facing integration guidance (MCP describe_integration + docs build).

INTEGRATION_GUIDES: Dict[str, Dict[str, Any]] = {
    "python": {
        "title": "Python callable / multi-stage list",
        "install_extra": None,
        "env_vars": [],
        "snippet": (
            "import retrieval_observatory as ro\n\n"
            "def retrieve(q: str) -> list[str]:\n"
            "    return my_index.search(q, k=100)\n\n"
            "report = ro.benchmark(retrieve, queries=queries, corpus=corpus, k=10)\n"
            "report.show()"
        ),
        "verify": "Run a 5-query smoke benchmark; expect metrics rows with pipeline_id set.",
    },
    "langchain": {
        "title": "LangChain retriever callback",
        "install_extra": "langchain",
        "env_vars": [],
        "snippet": (
            "from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback\n"
            "from retrieval_observatory.sdk.observe import observe_run\n\n"
            "with observe_run(run_id='prod-1', experiment_name='my-rag'):\n"
            "    docs = retriever.invoke(query, config={'callbacks': [RetobsLangChainCallback()]})\n"
            "# Push traces: retobs push-traces or REST POST /dbs/{id}/runs/{run_id}/traces"
        ),
        "verify": "After 1+ traced queries, call verify_integration — expect stages seen from callback spans.",
    },
    "llamaindex": {
        "title": "LlamaIndex query instrumentation",
        "install_extra": "llamaindex",
        "env_vars": [],
        "snippet": (
            "from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexHandler\n"
            "from retrieval_observatory.sdk.observe import observe_run\n\n"
            "handler = RetobsLlamaIndexHandler()\n"
            "with observe_run(run_id='prod-1', experiment_name='my-rag'):\n"
            "    index.as_query_engine(callback_manager=CallbackManager([handler])).query(q)"
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
            "# Option B — trace in-process (examples/fastapi_search/app.py):\n"
            "from retrieval_observatory.sdk.observe import observe_operator\n\n"
            "@observe_operator(op_id='bm25', op_type='SOURCE')\n"
            "def search(q: str): ..."
        ),
        "verify": "HTTP adapter: benchmark_config with adapter.http. In-process: verify_integration after traces.",
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


def list_integration_frameworks() -> List[str]:
    return sorted(INTEGRATION_GUIDES.keys())


def describe_integration(framework: Optional[str] = None) -> Dict[str, Any]:
    if framework is None:
        return {
            "frameworks": list_integration_frameworks(),
            "guides": INTEGRATION_GUIDES,
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
    guide["next"] = "Wire the snippet, run one query, then call verify_integration."
    return guide
