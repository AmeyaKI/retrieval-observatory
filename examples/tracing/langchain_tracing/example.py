"""Minimal LangChain-style retrieval tracing with retobs TraceRecorder.

Run (from repo root, with optional deps):
  pip install -e .
  python examples/tracing/langchain_tracing/example.py
"""
from __future__ import annotations

import asyncio

from retrieval_observatory.tracing import TraceRecorder, MemorySink
from retrieval_observatory.tracing.integrations.langchain import RetobsTraceHandler


async def main() -> None:
    sink = MemorySink()
    recorder = TraceRecorder(service="langchain-demo", sink=sink)
    handler = RetobsTraceHandler(recorder, pipeline_id="vector+bm25")

    handler.on_retriever_start("password reset policy 2024")
    handler.on_retriever_end(
        [
            {"id": "doc-1", "text": "To reset your password, open Settings…", "score": 0.91},
            {"id": "doc-2", "text": "Account recovery options…", "score": 0.77},
        ],
        latency_ms=34.2,
        stage_id="hybrid_retriever",
    )
    await handler.on_retriever_finish()

    trace = sink.traces[0]
    print(f"Recorded trace {trace.trace_id}: {len(trace.snapshots)} stage(s), status={trace.status}")


if __name__ == "__main__":
    asyncio.run(main())
