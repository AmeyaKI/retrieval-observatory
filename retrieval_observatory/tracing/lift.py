from __future__ import annotations

from typing import List

from retrieval_observatory.tracing.candidates import build_candidate_transition
from retrieval_observatory.tracing.model_v2 import (
    Candidate,
    OperatorSpan,
    RetrievalTraceV2,
    TraceTiming,
    critical_path_latency_ms,
)
from retrieval_observatory.types import PipelineResult, StageSnapshot


def _candidate(doc, op_id: str, *, origin_op_ids: List[str] | None = None) -> Candidate:
    return Candidate(
        doc_id=doc.id,
        score=float(doc.score),
        rank=int(doc.rank),
        input_rank=None,
        output_rank=int(doc.rank),
        origin_op_ids=list(origin_op_ids or [op_id]),
    )


def _op_type(stage_id: str) -> str:
    name = stage_id.lower()
    if any(part in name for part in ("bm25", "sparse", "keyword", "dense", "embed", "vector", "semantic", "temporal", "recency", "time", "source", "sentence-transformer")):
        return "SOURCE"
    if "fuse" in name or "rrf" in name:
        return "FUSE"
    if "rerank" in name or "cross" in name or "cohere" in name or "llm_rerank" in name:
        return "RERANK"
    if "expand" in name or "expansion" in name or "sibling" in name or "entity" in name:
        return "EXPAND"
    if "filter" in name:
        return "FILTER"
    if "boost" in name:
        return "BOOST"
    if "gate" in name:
        return "GATE"
    if "transform" in name:
        return "TRANSFORM"
    return "RERANK"


def _replay_policy(stage_id: str, op_type: str) -> str:
    name = stage_id.lower()
    if op_type == "SOURCE":
        if any(part in name for part in ("bm25", "sparse", "keyword", "temporal", "recency", "time")):
            return "EXACT"
        return "NOT_REPLAYABLE"
    if op_type in {"FUSE", "BOOST", "FILTER", "EXPAND"}:
        return "EXACT"
    if op_type == "RERANK":
        return "OBSERVED_ABLATION"
    return "NOT_REPLAYABLE"


def _deterministic(stage_id: str, op_type: str) -> bool:
    return _replay_policy(stage_id, op_type) == "EXACT"


def _stage_span(
    snapshot: StageSnapshot,
    parent_ids: List[str],
    op_id: str,
    *,
    inputs: List[Candidate] | None = None,
    outputs: List[Candidate] | None = None,
    params: dict | None = None,
) -> OperatorSpan:
    replay_policy = "NOT_REPLAYABLE"
    op_type = _op_type(snapshot.stage_id)
    replay_policy = _replay_policy(snapshot.stage_id, op_type)
    return OperatorSpan(
        op_id=op_id,
        op_type=op_type,  # type: ignore[arg-type]
        op_name=snapshot.stage_id,
        parent_ids=parent_ids,
        status="FIRED",
        deterministic=_deterministic(snapshot.stage_id, op_type),
        replay_policy=replay_policy,  # type: ignore[arg-type]
        latency_ms=float(snapshot.latency_ms),
        inputs=list(inputs or []),
        outputs=list(outputs or [_candidate(doc, op_id=op_id) for doc in snapshot.documents]),
        params=params or {"candidate_count": snapshot.candidate_count or len(snapshot.documents)},
    )


def lift_pipeline_result(result: PipelineResult, run_id: str | None = None) -> RetrievalTraceV2:
    spans: List[OperatorSpan] = []
    last_op_id: str | None = None
    previous_outputs: List[Candidate] = []

    if not result.snapshots:
        empty_status = "ERROR" if result.status == "OK" else result.status
        return RetrievalTraceV2(
            trace_id=f"{run_id or 'unscoped'}:{result.query_id}:{result.pipeline_id}",
            run_id=run_id or "",
            query_id=result.query_id,
            query_text="",
            pipeline_id=result.pipeline_id,
            spans=[],
            total_latency_ms=float(result.total_latency_ms),
            timing=TraceTiming(
                wall_clock_ms=float(result.total_latency_ms),
                critical_path_ms=0.0,
                operator_sum_ms=0.0,
            ),
            status=empty_status,
            error_traceback=result.error_traceback or (
                "PipelineResult had no stage snapshots" if empty_status == "ERROR" else None
            ),
            final_op_id=None,
        )

    for snapshot in result.snapshots:
        op_id = f"stage_{snapshot.stage_index}_{snapshot.stage_id}"
        parent_ids = [last_op_id] if last_op_id else []

        if snapshot.arms:
            arm_spans: List[OperatorSpan] = []
            for idx, arm in enumerate(snapshot.arms):
                arm_id = f"{op_id}_arm_{idx}_{arm.stage_id}"
                arm_span = _stage_span(arm, parent_ids=parent_ids, op_id=arm_id, inputs=previous_outputs)
                arm_spans.append(arm_span)
                spans.append(arm_span)

            fused_inputs, fused_outputs = build_candidate_transition(
                input_groups={arm_span.op_id: arm_span.outputs for arm_span in arm_spans},
                output_items=snapshot.documents,
                op_id=op_id,
                op_type="FUSE",
            )
            span = _stage_span(
                snapshot,
                parent_ids=[arm_span.op_id for arm_span in arm_spans],
                op_id=op_id,
                inputs=fused_inputs,
                outputs=fused_outputs,
                params={"candidate_count": snapshot.candidate_count or len(snapshot.documents), "k": 60},
            )
            spans.append(span)
        else:
            inputs, outputs = build_candidate_transition(
                input_groups={last_op_id: previous_outputs} if last_op_id else {},
                output_items=snapshot.documents,
                op_id=op_id,
                op_type=_op_type(snapshot.stage_id),
            )
            span = _stage_span(snapshot, parent_ids=parent_ids, op_id=op_id, inputs=inputs, outputs=outputs)
            spans.append(span)

        last_op_id = op_id
        previous_outputs = list(span.outputs)

    if spans:
        expected = [d.id for d in result.snapshots[-1].documents]
        actual = [c.doc_id for c in spans[-1].outputs]
        if expected != actual:
            raise ValueError("Lifted trace final output does not match PipelineResult final stage output")

    operator_sum_ms = sum(max(0.0, span.latency_ms) for span in spans)
    return RetrievalTraceV2(
        trace_id=f"{run_id or 'unscoped'}:{result.query_id}:{result.pipeline_id}",
        run_id=run_id or "",
        query_id=result.query_id,
        query_text="",
        pipeline_id=result.pipeline_id,
        spans=spans,
        total_latency_ms=float(result.total_latency_ms),
        timing=TraceTiming(
            wall_clock_ms=float(result.total_latency_ms),
            critical_path_ms=critical_path_latency_ms(spans),
            operator_sum_ms=operator_sum_ms,
        ),
        status=result.status,
        error_traceback=result.error_traceback,
        final_op_id=spans[-1].op_id if spans else None,
    )
