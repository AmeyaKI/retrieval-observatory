import random
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import (
    OperatorSpan,
    RetrievalTrace,
    TraceTiming,
    critical_path_latency_ms,
)
from retrieval_observatory.tracing.sink import BufferedTraceSink


@dataclass
class TraceContext:
    recorder: "TraceRecorder"
    query_text: str
    pipeline_id: str
    query_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    sampled: bool = True
    spans: list[OperatorSpan] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def span(
        self,
        op_type: str,
        op_name: str,
        documents: Sequence[Any],
        latency_ms: float,
        *,
        op_id: str,
        parent_ids: Sequence[str] = (),
        **kwargs: Any,
    ) -> OperatorSpan | None:
        if not self.sampled:
            return None
        inputs = {
            parent: next((span.outputs for span in self.spans if span.op_id == parent), ()) for parent in parent_ids
        }
        transition = build_candidate_transition(
            input_groups=inputs, output_items=documents, op_id=op_id, op_type=op_type
        )
        span = OperatorSpan(
            op_id,
            op_type,
            op_name,
            tuple(parent_ids),
            "FIRED",
            latency_ms,
            transition.input_groups,
            transition.outputs,
            **kwargs,
        )
        self.spans.append(span)
        return span

    def build_trace(self, *, status: str = "OK", error: BaseException | None = None) -> RetrievalTrace:
        wall_clock_ms = (time.perf_counter() - self.started) * 1000
        finals = tuple(
            span.op_id
            for span in self.spans
            if span.op_id not in {parent for item in self.spans for parent in item.parent_ids}
        )
        return RetrievalTrace(
            trace_id=uuid.uuid4().hex,
            service_id=self.recorder.service,
            run_id=None,
            query_id=self.query_id or uuid.uuid4().hex,
            query_text=self.query_text,
            pipeline_id=self.pipeline_id,
            spans=tuple(self.spans),
            final_op_ids=finals if status == "OK" else (),
            timestamp=datetime.now(timezone.utc),
            status=status,
            timing=TraceTiming(
                wall_clock_ms, critical_path_latency_ms(self.spans), sum(span.latency_ms for span in self.spans)
            ),
            metadata=self.metadata,
            request_id=self.request_id,
            error_traceback="".join(traceback.format_exception(error)) if error else None,
        )


class _TraceCM:
    def __init__(self, context: TraceContext):
        self.context = context

    async def __aenter__(self) -> TraceContext:
        return self.context

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.context.recorder.finish(self.context, status="ERROR" if exc else "OK", error=exc)
        return False


class TraceRecorder:
    def __init__(self, service: str, sink: BufferedTraceSink, sample_rate: float = 1.0):
        self.service, self.sink, self.sample_rate = service, sink, sample_rate

    def start_trace(
        self,
        query_text: str,
        pipeline_id: str,
        query_id: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> TraceContext:
        return TraceContext(
            self,
            query_text,
            pipeline_id,
            query_id,
            metadata or {},
            request_id,
            self.sample_rate >= 1 or random.random() < self.sample_rate,
        )

    def trace(
        self,
        query_text: str,
        pipeline_id: str,
        query_id: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> _TraceCM:
        return _TraceCM(self.start_trace(query_text, pipeline_id, query_id, metadata, request_id))

    def finish(self, context: TraceContext, *, status: str = "OK", error: BaseException | None = None) -> None:
        if not context.sampled:
            self.sink.counters.sampled_out()
            return
        try:
            self.sink.offer(context.build_trace(status=status, error=error))
        except BaseException:
            self.sink.counters.serialization_failed()

    def health(self):
        return self.sink.health()
