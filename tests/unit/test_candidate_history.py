from __future__ import annotations

from retrieval_observatory.tracing.candidate_history import candidate_history
from dataclasses import replace

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def _fusion_rerank_trace() -> RetrievalTrace:
    """arm_a introduces d1,d2; arm_b introduces d2,d3; fuse merges; rerank keeps d2 only."""
    arm_a = OperatorSpan(
        op_id="arm_a", op_type="SOURCE", op_name="bm25", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["arm_a"]),
            Candidate(doc_id="d2", score=0.9, rank=2, origin_op_ids=["arm_a"]),
        ],
    )
    arm_b = OperatorSpan(
        op_id="arm_b", op_type="SOURCE", op_name="dense", parent_ids=[],
        status="FIRED", deterministic=False, replay_policy="NOT_REPLAYABLE", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d2", score=0.8, rank=1, origin_op_ids=["arm_b"]),
            Candidate(doc_id="d3", score=0.7, rank=2, origin_op_ids=["arm_b"]),
        ],
    )
    fuse = OperatorSpan(
        op_id="fuse", op_type="FUSE", op_name="rrf", parent_ids=["arm_a", "arm_b"],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        outputs=[
            Candidate(doc_id="d2", score=0.5, rank=1, origin_op_ids=["arm_a", "arm_b"]),
            Candidate(doc_id="d1", score=0.3, rank=2, origin_op_ids=["arm_a"]),
            Candidate(doc_id="d3", score=0.3, rank=3, origin_op_ids=["arm_b"]),
        ],
    )
    rerank = OperatorSpan(
        op_id="rerank", op_type="RERANK", op_name="cross_encoder", parent_ids=["fuse"],
        status="FIRED", deterministic=False, replay_policy="OBSERVED_ABLATION", latency_ms=1.0,
        outputs=[Candidate(doc_id="d2", score=2.0, rank=1, origin_op_ids=["arm_a", "arm_b"])],
    )
    return RetrievalTrace(
        trace_id="t1", service_id="test", run_id="r1", query_id="q1", query_text="q", pipeline_id="p1",
        spans=[arm_a, arm_b, fuse, rerank], timing=TraceTiming(4.0, 4.0, 4.0), final_op_ids=("rerank",),
    )


def test_survivor_history_tracks_promotion():
    hist = candidate_history(_fusion_rerank_trace(), "d2")
    assert hist.survived is True
    assert hist.final_rank == 1
    assert hist.introduced_at == "arm_a"
    assert hist.dropped_at is None
    events = [e.event for e in hist.events]
    assert events[0] == "introduced"
    assert "passed" in events


def test_dropped_by_rerank_is_attributed():
    hist = candidate_history(_fusion_rerank_trace(), "d1")
    assert hist.survived is False
    assert hist.dropped_at == "rerank"
    assert hist.dropped_reason == "reranked_out"
    drop_events = [e for e in hist.events if e.event == "dropped"]
    assert len(drop_events) == 1
    assert drop_events[0].drop_reason_inferred is True


def test_introduced_by_correct_arm():
    hist = candidate_history(_fusion_rerank_trace(), "d3")
    assert hist.introduced_at == "arm_b"
    assert hist.introduced_by_arms == ["arm_b"]
    # d3 present at fuse, gone at rerank
    assert hist.dropped_at == "rerank"


def test_explicit_drop_reason_is_honored():
    trace = _fusion_rerank_trace()
    # Stamp an explicit drop reason on d1 as it enters rerank.
    trace.spans = (*trace.spans[:3], replace(
        trace.spans[3],
        input_groups={"fuse": (Candidate(doc_id="d1", score=0.3, rank=2, drop_reason="filtered"),)},
    ))
    hist = candidate_history(trace, "d1")
    drop = [e for e in hist.events if e.event == "dropped"][0]
    assert drop.drop_reason == "filtered"
    assert drop.drop_reason_inferred is False


def test_unknown_doc_has_empty_history():
    hist = candidate_history(_fusion_rerank_trace(), "does_not_exist")
    assert hist.events == []
    assert hist.survived is False
    assert hist.introduced_at is None
