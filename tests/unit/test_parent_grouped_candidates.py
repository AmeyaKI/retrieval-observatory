from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model import Candidate, OperatorSpan
from retrieval_observatory.pipeline.graph_contract import PipelineGraphNode, GraphNodeMetrics


def test_operator_span_roundtrip_preserves_parent_groups() -> None:
    sparse = Candidate(doc_id="s1", rank=1, score=4.0, origin_op_ids=("bm25",))
    dense = Candidate(doc_id="d1", rank=1, score=0.9, origin_op_ids=("dense",))
    span = OperatorSpan(
        op_id="fuse",
        op_type="FUSE",
        op_name="fusion",
        parent_ids=("bm25", "dense"),
        input_groups={"bm25": (sparse,), "dense": (dense,)},
        outputs=(sparse, dense),
        status="FIRED",
        latency_ms=1.0,
    )
    restored = OperatorSpan.from_dict(span.to_dict())
    assert tuple(restored.input_groups) == ("bm25", "dense")
    assert restored.input_groups["dense"][0].doc_id == "d1"
    assert "inputs" not in span.to_dict()


def test_transition_preserves_group_identity() -> None:
    candidate = Candidate("d1", 0.8, 1, origin_op_ids=("dense",))
    transition = build_candidate_transition(
        input_groups={"dense": (candidate,)},
        output_items=[{"doc_id": "d1", "score": 1.0, "rank": 1}],
        op_id="rerank",
        op_type="RERANK",
    )
    assert transition.input_groups["dense"][0].doc_id == candidate.doc_id
    assert transition.outputs[0].doc_id == "d1"


def test_graph_node_serializes_parent_candidate_counts() -> None:
    node = PipelineGraphNode(
        "fuse", "fusion", "FUSE", 1, None, 2, GraphNodeMetrics(), parent_candidate_counts={"dense": 1, "sparse": 1}
    )
    assert node.to_dict()["parent_candidate_counts"] == {"dense": 1, "sparse": 1}
