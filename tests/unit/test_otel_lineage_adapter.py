from __future__ import annotations

from retrieval_observatory.tracing.adapters.otel import normalize_otel_retrieval_trace


def _otel_span_without_candidate_parents() -> dict:
    return {
        "trace_id": "otel-trace",
        "span_id": "otel-span",
        "name": "fusion",
        "attributes": {
            "service.name": "search-api",
            "retobs.run_id": "run-1",
            "retobs.query_id": "query-1",
            "retobs.pipeline_id": "hybrid",
            "retobs.operator.id": "fusion",
            "retobs.operator.type": "FUSE",
            "retobs.candidates.outputs": [
                {
                    "candidate_id": "fused-1",
                    "logical_chunk_id": "chunk-1",
                    "doc_id": "doc-1",
                    "score": 0.9,
                    "rank": 1,
                    "decision_reason": "fused",
                }
            ],
        },
    }


def test_otel_adapter_marks_missing_parentage_partial() -> None:
    trace = normalize_otel_retrieval_trace(_otel_span_without_candidate_parents())

    assert trace.capture.lineage_evidence == "partial"
    assert trace.spans[0].outputs[0].parent_candidate_ids == ()
    assert trace.spans[0].outputs[0].decision_evidence == "partial"


def test_otel_adapter_maps_only_explicit_lineage_attributes() -> None:
    trace = normalize_otel_retrieval_trace(
        {
            "trace_id": "otel-trace",
            "span_id": "retrieve-span",
            "name": "retrieve",
            "attributes": {
                "service.name": "search-api",
                "retobs.run_id": "run-1",
                "retobs.query_id": "query-1",
                "retobs.query_text": "local-only query",
                "retobs.pipeline_id": "hybrid",
                "retobs.operator.id": "retrieve",
                "retobs.operator.type": "SOURCE",
                "retobs.candidates.outputs": [
                    {
                        "candidate_id": "candidate-1",
                        "logical_chunk_id": "chunk-1",
                        "doc_id": "doc-1",
                        "score": 0.9,
                        "rank": 1,
                    }
                ],
            },
        }
    )

    assert trace.query_text == "local-only query"
    assert trace.spans[0].parent_ids == ()
    assert trace.spans[0].input_groups == {}
    assert trace.spans[0].outputs[0].parent_candidate_ids == ()
    assert trace.capture.lineage_evidence == "recorded"
