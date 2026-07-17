from __future__ import annotations

from dataclasses import replace

import pytest

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming
from retrieval_observatory.tracing.replay import ReplayAssumptions, replay_assumptions


def _span(op_id, op_type, parents, policy="EXACT", **kw):
    return OperatorSpan(
        op_id=op_id, op_type=op_type, op_name=op_id, parent_ids=parents,
        status="FIRED", deterministic=policy == "EXACT", replay_policy=policy,
        latency_ms=1.0, **kw,
    )


def _fusion_trace() -> RetrievalTrace:
    arm = _span("arm_bm25", "SOURCE", [], outputs=[Candidate(doc_id="d1", score=1.0, rank=1, origin_op_ids=["arm_bm25"])])
    arm2 = _span("arm_dense", "SOURCE", [], policy="NOT_REPLAYABLE",
                 outputs=[Candidate(doc_id="d2", score=0.9, rank=1, origin_op_ids=["arm_dense"])])
    fuse = _span("fuse", "FUSE", ["arm_bm25", "arm_dense"],
                 outputs=[Candidate(doc_id="d1", score=0.5, rank=1, origin_op_ids=["arm_bm25", "arm_dense"])])
    fuse = replace(fuse, params={"k": 42})
    return RetrievalTrace(
        trace_id="t", service_id="svc", run_id="r", query_id="q", query_text="q", pipeline_id="p",
        spans=[arm, arm2, fuse], timing=TraceTiming(3.0, 3.0, 3.0), final_op_ids=("fuse",),
    )


def test_fuse_source_uses_rrf_recompute():
    a = replay_assumptions(_fusion_trace(), "arm_bm25")
    assert isinstance(a, ReplayAssumptions)
    assert a.strategy == "fuse_rrf_recompute"
    assert a.rrf_recomputed is True
    assert a.rrf_k == 42
    assert a.caveats  # non-empty human-readable copy


def test_rerank_uses_passthrough_inputs():
    rerank = _span("rerank", "RERANK", ["src"], policy="OBSERVED_ABLATION",
                   outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    src = _span("src", "SOURCE", [], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    trace = RetrievalTrace(trace_id="t", service_id="svc", run_id="r", query_id="q", query_text="q",
                             pipeline_id="p", spans=[src, rerank], timing=TraceTiming(2.0, 2.0, 2.0), final_op_ids=("rerank",))
    a = replay_assumptions(trace, "rerank")
    assert a.strategy == "rerank_passthrough_inputs"
    assert a.rrf_recomputed is False
    assert a.replay_policy == "OBSERVED_ABLATION"


def test_missing_op_raises():
    with pytest.raises(ValueError):
        replay_assumptions(_fusion_trace(), "nope")
