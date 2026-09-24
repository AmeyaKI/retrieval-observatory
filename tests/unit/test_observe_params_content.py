"""``@observe`` span params record configuration, never the candidate arguments' document content."""

from __future__ import annotations

import json

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace
from retrieval_observatory.tracing.capture import CaptureSpec

SENTINEL = "SENTINEL-DOC-TEXT-7f3a"


@observe("SOURCE", op_id="dense")
def dense(query: str) -> list[dict]:
    return [{"id": "d1", "text": SENTINEL, "score": 1.0}, {"id": "d2", "text": "other", "score": 0.5}]


@observe("SOURCE", op_id="lexical")
def lexical(query: str) -> list[dict]:
    return [{"id": "d3", "text": SENTINEL, "score": 1.0}]


def _trace_of(call) -> dict:
    start_trace(ObserveContext(None, "q1", "query", "app"))
    call()
    return finish_trace().to_dict()


def test_argument_named_by_a_capture_input_mapping_is_not_copied_into_params() -> None:
    @observe("RERANK", op_id="rerank", parent_ids=("dense",), capture=CaptureSpec(inputs=lambda bound: {"dense": list(bound.arguments["dense_hits"])}))
    def rerank(query: str, dense_hits: list[dict], top_k: int, weights: list[float]) -> list[dict]:
        return dense_hits[:top_k]

    trace = _trace_of(lambda: rerank("query", dense_hits=dense("query"), top_k=1, weights=[0.7, 0.3]))

    span = next(span for span in trace["spans"] if span["op_id"] == "rerank")
    assert span["input_capture"] == "recorded" and trace["capture_failures"] == []
    assert span["params"] == {"top_k": 1, "weights": [0.7, 0.3]}
    assert SENTINEL not in json.dumps(trace)


def test_mapping_of_lanes_read_by_a_capture_input_mapping_is_not_copied_into_params() -> None:
    lanes_to_parents = CaptureSpec(inputs=lambda bound: {"dense": bound.arguments["by_lane"]["semantic"], "lexical": bound.arguments["by_lane"]["keyword"]})

    @observe("FUSE", op_id="fuse", parent_ids=("dense", "lexical"), capture=lanes_to_parents)
    def fuse(query: str, by_lane: dict[str, list[dict]], rrf_k: int) -> list[dict]:
        return [*by_lane["semantic"], *by_lane["keyword"]]

    trace = _trace_of(lambda: fuse("query", by_lane={"semantic": dense("query"), "keyword": lexical("query")}, rrf_k=60))

    span = next(span for span in trace["spans"] if span["op_id"] == "fuse")
    assert span["input_capture"] == "recorded"
    assert span["params"] == {"rrf_k": 60}
    assert SENTINEL not in json.dumps(trace)
