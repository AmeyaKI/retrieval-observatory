"""Minimal LlamaIndex-style retrieval tracing with retobs TraceRecorder.

Run (from repo root):
  pip install -e .
  python examples/tracing/llamaindex_tracing/example.py
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from retrieval_observatory.tracing import TraceRecorder, MemorySink
from retrieval_observatory.tracing.integrations.llamaindex import RetobsLlamaIndexHandler


@dataclass
class FakeNode:
    node_id: str
    text: str
    score: float


async def main() -> None:
    sink = MemorySink()
    recorder = TraceRecorder(service="llamaindex-demo", sink=sink)
    handler = RetobsLlamaIndexHandler(recorder, pipeline_id="index-query")

    handler.on_retrieve_start("compare refund policy 2023 vs 2024")
    await handler.on_retrieve_end(
        [
            FakeNode("n1", "Refund policy updated in 2024…", 0.88),
            FakeNode("n2", "2023 refunds excluded for digital goods…", 0.71),
        ],
        latency_ms=41.0,
        stage_id="vector_store",
    )

    trace = sink.traces[0]
    print(f"Recorded trace {trace.trace_id}: {len(trace.final_results)} hit(s)")


if __name__ == "__main__":
    asyncio.run(main())
