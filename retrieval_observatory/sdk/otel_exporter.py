from __future__ import annotations

from typing import Any

from retrieval_observatory.tracing.model import RetrievalTrace


def export_trace_to_otel(trace: RetrievalTrace, tracer: Any) -> None:
    """Export a RetrievalTrace into OpenTelemetry spans.

    `tracer` is an OpenTelemetry tracer instance (from `trace.get_tracer(...)`).
    """
    with tracer.start_as_current_span(
        name=f"retobs.trace.{trace.pipeline_id}",
        attributes={
            "retobs.trace_id": trace.trace_id,
            "retobs.run_id": trace.run_id,
            "retobs.query_id": trace.query_id,
            "retobs.pipeline_id": trace.pipeline_id,
            "retobs.status": trace.status,
            "retobs.trace_schema_version": trace.schema_version,
        },
    ) as root:
        for span in trace.spans:
            with tracer.start_as_current_span(
                name=f"retobs.op.{span.op_name}",
                context=root.get_span_context(),
                attributes={
                    "retobs.op_id": span.op_id,
                    "retobs.op_type": span.op_type,
                    "retobs.status": span.status,
                    "retobs.replay_policy": span.replay_policy,
                    "retobs.latency_ms": span.latency_ms,
                    "retobs.input_variant": span.input_variant,
                },
            ) as op_span:
                for candidate in span.outputs:
                    op_span.add_event(
                        "retobs.candidate",
                        {
                            "retobs.doc_id": candidate.doc_id,
                            "retobs.score": candidate.score,
                            "retobs.rank": candidate.rank,
                        },
                    )
