"""OpenAI Agents SDK + retobs tracing example.

Demonstrates wrap_retrieval_tool: wrap the plain Python function registered as an agent's
retrieval tool, so every call it makes (whether invoked directly, as here, or by a real
agent loop) is traced.

Requirements:
    pip install retrieval-observatory[openai-agents,dashboard]
    pip install openai-agents   # only needed to run a real Agent/Runner loop, see below

Usage:
    python examples/integrations/openai_agents_search/app.py
    retobs serve --db .retobs/openai_agents_demo.db

NOTE: running a full `Agent` + `Runner.run_sync(...)` loop requires OPENAI_API_KEY and a
live model call, so this example calls the wrapped tool function directly instead --
exactly what the SDK does internally when the agent decides to invoke the tool, and enough
to prove tracing works end-to-end without any external service. To wire this into a real
agent, wrap the function with `agents.function_tool` after wrapping it with
`wrap_retrieval_tool` (see the commented-out block below) and pass it to `Agent(tools=[...])`.
"""
from __future__ import annotations

import asyncio
import uuid

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.integrations.openai_agents import wrap_retrieval_tool

CORPUS = [
    {"id": "d0", "text": "BM25 is a bag-of-words retrieval function that ranks documents based on term frequency."},
    {"id": "d1", "text": "Dense retrieval uses bi-encoder models to embed queries into a shared vector space."},
    {"id": "d2", "text": "Hybrid search combines BM25 and dense retrieval scores via reciprocal rank fusion."},
]
QUERIES = ["What is BM25?", "How does hybrid search work?"]
DB_PATH = ".retobs/openai_agents_demo.db"
RUN_ID = "openai-agents-demo"


def kb_search(query: str) -> list[dict]:
    """The retrieval tool an agent would call. Naive term-overlap ranking -- no external
    service or API key required to demonstrate the tracing wrapper."""
    terms = set(query.lower().split())
    scored = sorted(CORPUS, key=lambda d: -len(terms & set(d["text"].lower().split())))
    return scored[:3]


async def main() -> None:
    import os

    os.makedirs(".retobs", exist_ok=True)
    store = SQLiteStore(DB_PATH)
    await store.init_db()
    await store.save_run(RUN_ID, "openai-agents-demo", "{}")

    traced_kb_search = wrap_retrieval_tool(kb_search, op_id="kb_search")

    # To wire this into a real agent loop (requires OPENAI_API_KEY):
    #
    #   from agents import Agent, Runner, function_tool
    #   kb_search_tool = function_tool(traced_kb_search)
    #   agent = Agent(name="retriever-agent", instructions="Answer using kb_search.", tools=[kb_search_tool])
    #   result = Runner.run_sync(agent, "What is BM25?")

    print(f"Running {len(QUERIES)} queries through a wrapped retrieval tool …")
    for query in QUERIES:
        start_trace(ObserveContext(
            run_id=RUN_ID, query_id=f"q_{uuid.uuid4().hex[:8]}", query_text=query, pipeline_id="agent_kb_search",
        ))
        result = traced_kb_search(query)
        trace = finish_trace()
        await store.save_trace_v2(trace)
        print(f"  ✓ {query!r}  ({len(result)} docs, {len(trace.spans)} span(s))")

    print(f"\nTraces written to {DB_PATH}")
    print(f"Run: retobs serve --db {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
