import pytest

from retrieval_observatory.tracing import TraceRecorder, MemorySink
from retrieval_observatory.tracing.integrations.langchain import RetobsTraceHandler


@pytest.mark.asyncio
async def test_langchain_handler_records_retrieval_stages():
    sink = MemorySink()
    recorder = TraceRecorder(service="lc-svc", sink=sink, sample_rate=1.0)
    handler = RetobsTraceHandler(recorder, pipeline_id="lc-pipeline")

    handler.on_retriever_start("how do I reset my password?", metadata={"source": "test"})
    handler.on_retriever_end(
        [{"id": "d1", "text": "reset steps", "score": 0.95}],
        latency_ms=12.5,
        stage_id="vector",
    )
    await handler.on_retriever_finish()

    assert len(sink.traces) == 1
    trace = sink.traces[0]
    assert trace.query_text == "how do I reset my password?"
    assert trace.pipeline_id == "lc-pipeline"
    assert trace.status == "OK"
    assert len(trace.snapshots) == 1
    assert trace.snapshots[0].stage_id == "vector"
    assert trace.final_results[0].id == "d1"
