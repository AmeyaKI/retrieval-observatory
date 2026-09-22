import random
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.capture import incomplete_boundary_count, snapshot
from retrieval_observatory.tracing.model import (
    CaptureMetadata,
    OperatorSpan,
    RetrievalTrace,
    TraceTiming,
    critical_path_latency_ms,
    latest_span_of,
    next_node_id,
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
    capture_failures: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)
    # The trace that was active in ``sdk.observe`` before this context was bound there.
    _observe_previous: Any = field(default=None, repr=False, compare=False)

    def span(
        self,
        op_type: str,
        op_name: str,
        documents: Sequence[Any],
        latency_ms: float,
        *,
        op_id: str,
        parent_ids: Sequence[str] = (),
        input_groups: Mapping[str, Sequence[Any]] | None = None,
        invocation_id: str | None = None,
        **kwargs: Any,
    ) -> OperatorSpan | None:
        """Record a fired span. Without ``input_groups`` (the operator's actual inputs) the inputs
        are reconstructed from the parent spans' outputs and labelled ``inferred``. ``op_id`` names
        the operator; a repeated invocation gets its own node (``op_id#2``). A declared parent
        resolves to that operator's latest invocation; ``invocation_id`` is the framework's own
        run id when it has one."""
        if not self.sampled:
            return None
        node_id = next_node_id((span.op_id for span in self.spans), op_id)
        parents = {parent: latest_span_of(self.spans, parent) for parent in parent_ids}
        node_of = {parent: span.op_id if span is not None else parent for parent, span in parents.items()}
        invocation_ids = tuple(span.invocation_id for span in parents.values() if span is not None)
        if input_groups is not None:
            inputs = {node_of.get(parent, parent): snapshot(items, node_of.get(parent, parent)) for parent, items in input_groups.items()}
            input_capture, parent_linkage = "recorded", "declared"
        else:
            inputs = {node_of[parent]: span.outputs if span is not None else () for parent, span in parents.items()}
            input_capture, parent_linkage = ("inferred", "inferred") if parent_ids else ("not_applicable", "recorded")
        transition = build_candidate_transition(
            input_groups=inputs, output_items=documents, op_id=node_id, op_type=op_type
        )
        span = OperatorSpan(
            node_id,
            op_type,
            op_name,
            tuple(node_of[parent] for parent in parent_ids),
            "FIRED",
            latency_ms,
            transition.input_groups,
            transition.outputs,
            input_capture=input_capture,
            invocation_id=invocation_id or uuid.uuid4().hex,
            operator_id=op_id,
            parent_invocation_ids=invocation_ids if len(invocation_ids) == len(parents) and all(invocation_ids) else (),
            parent_linkage=parent_linkage,
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
            capture=CaptureMetadata(incomplete_boundary_count=incomplete_boundary_count(self.spans)),
            metadata=self.metadata,
            request_id=self.request_id,
            error_traceback="".join(traceback.format_exception(error)) if error else None,
            capture_failures=tuple(self.capture_failures),
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
        context = TraceContext(
            self,
            query_text,
            pipeline_id,
            query_id,
            metadata or {},
            request_id,
            self.sample_rate >= 1 or random.random() < self.sample_rate,
        )
        if context.sampled:
            # Bridge to the decorator path: ``@observe`` functions called while this context is
            # open append their spans here instead of silently recording nothing.
            from retrieval_observatory.sdk.observe import bind_active_trace

            context._observe_previous = bind_active_trace(context)
        return context

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
        from retrieval_observatory.sdk.observe import release_active_trace

        release_active_trace(context, context._observe_previous)
        if not context.sampled:
            self.sink.counters.sampled_out()
            return
        try:
            self.sink.offer(context.build_trace(status=status, error=error))
        except BaseException:
            self.sink.counters.serialization_failed()

    def health(self):
        return self.sink.health()
