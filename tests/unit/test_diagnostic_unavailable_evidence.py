from dataclasses import replace

from retrieval_observatory.diagnostics import CandidateHistoryIndex
from retrieval_observatory.tracing.model import Candidate, CaptureMetadata, OperatorSpan, RetrievalTrace


def test_history_preserves_parent_group_and_explicit_drop() -> None:
    source = OperatorSpan.source("dense", "dense", [Candidate("gold", 1, 1)])
    filt = OperatorSpan(
        "filter", "FILTER", "filter", ("dense",), "FIRED", 1,
        {"dense": (replace(source.outputs[0], drop_reason="outside_time_window"),)}, (),
    )
    trace = RetrievalTrace("t", "svc", "r", "q", "q", "p", (source, filt), ("filter",))
    event = CandidateHistoryIndex.build(trace).for_document("gold")[-1]
    assert event.input_parents == ("dense",)
    assert event.state == "removed"
    assert event.drop_reason == "outside_time_window"


def test_truncated_capture_marks_history_incomplete() -> None:
    source = OperatorSpan.source("source", "source", [Candidate("d", 1, 1)])
    trace = RetrievalTrace(
        "t", "svc", "r", "q", "q", "p", (source,), ("source",),
        capture=CaptureMetadata(candidates_truncated=True),
    )
    history = CandidateHistoryIndex.build(trace)
    assert history.complete is False
    assert history.limitations == ("candidate_payload_truncated",)
