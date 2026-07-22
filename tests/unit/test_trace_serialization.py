import json
from datetime import datetime, timezone
from uuid import UUID

from retrieval_observatory.tracing.config import PayloadLimits
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace
from retrieval_observatory.tracing.serialization import normalize_trace


def _trace(*, metadata=None, candidate_count: int = 0) -> RetrievalTrace:
    candidates = tuple(
        Candidate(str(index), 1.0, index + 1, metadata={"text": "x" * 20})
        for index in range(candidate_count)
    )
    return RetrievalTrace(
        "trace",
        "svc",
        None,
        "query",
        "hello",
        "pipeline",
        (OperatorSpan.source("source", "source", candidates),),
        ("source",),
        datetime.now(timezone.utc),
        metadata=metadata or {},
    )


def test_normalize_handles_non_json_metadata() -> None:
    trace = _trace(
        metadata={
            "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "ids": {UUID(int=1)},
            "blob": b"abc",
        }
    )
    normalized = normalize_trace(trace, limits=PayloadLimits(), redacted_keys=frozenset())
    json.dumps(normalized.payload)
    assert normalized.payload["metadata"]["blob"] == "<bytes:3>"


def test_candidate_count_and_payload_size_are_bounded() -> None:
    normalized = normalize_trace(
        _trace(candidate_count=5),
        limits=PayloadLimits(max_candidates_per_span=2, max_payload_bytes=10_000),
        redacted_keys=frozenset(),
    )
    assert len(normalized.payload["spans"][0]["outputs"]) == 2
    assert normalized.report.omitted_candidates == 3
    assert normalized.payload["capture"]["candidates_truncated"] is True


def test_irreducibly_oversized_payload_fails() -> None:
    normalized = normalize_trace(
        _trace(metadata={"large": "x" * 100}),
        limits=PayloadLimits(max_payload_bytes=10, max_string_chars=100),
        redacted_keys=frozenset(),
    )
    assert normalized.failed is True


def test_normalize_preserves_candidate_lineage_fields() -> None:
    candidate = Candidate(
        "chunk:42",
        0.9,
        1,
        candidate_id="fused:42",
        logical_chunk_id="chunk:42",
        parent_candidate_ids=("lex:42", "vec:42"),
        document_id="doc:7",
        document_revision="rev:3",
        content_hash="sha256:abc",
        char_start=10,
        char_end=20,
    )
    trace = RetrievalTrace(
        "trace",
        "svc",
        None,
        "query",
        "hello",
        "pipeline",
        (OperatorSpan.source("source", "source", (candidate,)),),
        ("source",),
        datetime.now(timezone.utc),
    )

    normalized = normalize_trace(trace, limits=PayloadLimits(), redacted_keys=frozenset())
    restored = RetrievalTrace.from_dict(normalized.payload)

    assert restored.spans[0].outputs[0] == candidate
