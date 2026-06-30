from __future__ import annotations

from typing import List

from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
from retrieval_observatory.types import PipelineResult, StageSnapshot


def _candidate(doc, op_id: str) -> Candidate:
    return Candidate(
        doc_id=doc.id,
        score=float(doc.score),
        rank=int(doc.rank),
        origin_op_ids=[op_id],
    )


def _op_type(stage_id: str) -> str:
    name = stage_id.lower()
    if "bm25" in name or "dense" in name or "source" in name:
        return "SOURCE"
    if "fuse" in name or "rrf" in name:
        return "FUSE"
    if "boost" in name:
        return "BOOST"
    if "expand" in name:
        return "EXPAND"
    if "filter" in name:
        return "FILTER"
    if "gate" in name:
        return "GATE"
    if "transform" in name:
        return "TRANSFORM"
    return "RERANK"


def _stage_span(snapshot: StageSnapshot, parent_ids: List[str], op_id: str) -> OperatorSpan:
    replay_policy = "NOT_REPLAYABLE"
    op_type = _op_type(snapshot.stage_id)
    if op_type in {"FUSE", "BOOST", "FILTER"}:
        replay_policy = "EXACT"
    elif op_type == "RERANK":
        replay_policy = "OBSERVED_ABLATION"
    return OperatorSpan(
        op_id=op_id,
        op_type=op_type,  # type: ignore[arg-type]
        op_name=snapshot.stage_id,
        parent_ids=parent_ids,
        status="FIRED",
        deterministic=op_type in {"SOURCE", "FUSE", "BOOST", "FILTER"},
        replay_policy=replay_policy,  # type: ignore[arg-type]
        latency_ms=float(snapshot.latency_ms),
        outputs=[_candidate(doc, op_id=op_id) for doc in snapshot.documents],
        params={"candidate_count": snapshot.candidate_count or len(snapshot.documents)},
    )


def lift_pipeline_result(result: PipelineResult, run_id: str | None = None) -> RetrievalTraceV2:
    spans: List[OperatorSpan] = []
    last_op_id: str | None = None
    for snapshot in result.snapshots:
        op_id = f"stage_{snapshot.stage_index}_{snapshot.stage_id}"
        parent_ids = [last_op_id] if last_op_id else []
        span = _stage_span(snapshot, parent_ids=parent_ids, op_id=op_id)
        spans.append(span)
        for arm in snapshot.arms:
            arm_id = f"stage_{snapshot.stage_index}_{arm.stage_id}"
            arm_span = _stage_span(arm, parent_ids=[op_id], op_id=arm_id)
            spans.append(arm_span)
        last_op_id = op_id

    if result.snapshots and spans:
        expected = [d.id for d in result.snapshots[-1].documents]
        actual = [c.doc_id for c in spans[-1].outputs]
        if expected != actual:
            raise ValueError("Lifted trace final output does not match PipelineResult final stage output")

    return RetrievalTraceV2(
        trace_id=f"{result.query_id}:{result.pipeline_id}",
        run_id=run_id or "",
        query_id=result.query_id,
        query_text="",
        pipeline_id=result.pipeline_id,
        spans=spans,
        total_latency_ms=float(result.total_latency_ms),
        status=result.status,
        error_traceback=result.error_traceback,
    )
