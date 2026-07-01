from __future__ import annotations

import contextvars
import functools
import time
import uuid
from asyncio import iscoroutinefunction
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2

_current_trace: contextvars.ContextVar[RetrievalTraceV2 | None] = contextvars.ContextVar(
    "retobs_current_trace",
    default=None,
)


@dataclass
class ObserveContext:
    run_id: str
    query_id: str
    query_text: str
    pipeline_id: str
    request_id: Optional[str] = None


def start_trace(
    ctx: ObserveContext,
    *,
    metadata: Dict[str, Any] | None = None,
    request_id: str | None = None,
    pipeline_id: str | None = None,
    query_id: str | None = None,
) -> RetrievalTraceV2:
    trace = RetrievalTraceV2(
        trace_id=uuid.uuid4().hex,
        run_id=ctx.run_id,
        query_id=query_id or ctx.query_id,
        query_text=ctx.query_text,
        pipeline_id=pipeline_id or ctx.pipeline_id,
        spans=[],
        total_latency_ms=0.0,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata or {},
        request_id=request_id or ctx.request_id,
    )
    _current_trace.set(trace)
    return trace


def finish_trace(status: str = "OK", error_traceback: str | None = None) -> RetrievalTraceV2:
    trace = _current_trace.get()
    if trace is None:
        raise RuntimeError("finish_trace() called without an active trace")
    trace.status = status  # type: ignore[assignment]
    trace.error_traceback = error_traceback
    trace.total_latency_ms = sum(span.latency_ms for span in trace.spans)
    if trace.spans:
        trace.final_op_id = trace.spans[-1].op_id
    return trace


def _to_candidates(value: Any, op_id: str) -> List[Candidate]:
    items: List[Candidate] = []
    if isinstance(value, list):
        for idx, item in enumerate(value, start=1):
            if hasattr(item, "doc_id"):
                items.append(
                    Candidate(
                        doc_id=str(item.doc_id),
                        score=float(getattr(item, "score", 0.0)),
                        rank=int(getattr(item, "rank", idx)),
                        origin_op_ids=[op_id],
                    )
                )
            elif hasattr(item, "id"):
                items.append(
                    Candidate(
                        doc_id=str(item.id),
                        score=float(getattr(item, "score", 0.0)),
                        rank=int(getattr(item, "rank", idx)),
                        origin_op_ids=[op_id],
                    )
                )
            elif isinstance(item, dict):
                doc_id = str(item.get("doc_id") or item.get("id", idx))
                items.append(
                    Candidate(
                        doc_id=doc_id,
                        score=float(item.get("score", 0.0)),
                        rank=int(item.get("rank", idx)),
                        origin_op_ids=[op_id],
                    )
                )
            elif isinstance(item, str):
                items.append(Candidate(doc_id=item, score=0.0, rank=idx, origin_op_ids=[op_id]))
    return items


def observe(
    op_type: str,
    *,
    op_id: str | None = None,
    op_name: str | None = None,
    parent_ids: List[str] | None = None,
    deterministic: bool = False,
    replay_policy: str = "NOT_REPLAYABLE",
    input_variant: str = "raw",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _build_span(
            trace: RetrievalTraceV2 | None,
            resolved_op_id: str,
            resolved_parent_ids: List[str],
            elapsed: float,
            result: Any,
            status: str,
            err: str | None,
            kwargs: Dict[str, Any],
        ) -> None:
            if trace is None:
                return
            trace.spans.append(
                OperatorSpan(
                    op_id=resolved_op_id,
                    op_type=op_type,  # type: ignore[arg-type]
                    op_name=op_name or fn.__name__,
                    parent_ids=list(resolved_parent_ids),
                    status=status,  # type: ignore[arg-type]
                    deterministic=deterministic,
                    replay_policy=replay_policy,  # type: ignore[arg-type]
                    latency_ms=elapsed,
                    inputs=_to_candidates(kwargs.get("documents") or kwargs.get("docs"), op_id=resolved_op_id),
                    outputs=_to_candidates(result, op_id=resolved_op_id),
                    params={k: v for k, v in kwargs.items() if k not in {"documents", "docs"}},
                    input_variant=input_variant,
                    error=err,
                )
            )

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            trace = _current_trace.get()
            start = time.perf_counter()
            resolved_parents = kwargs.pop("parent_ids", None) or parent_ids or (
                [trace.spans[-1].op_id] if trace and trace.spans else []
            )
            resolved_id = kwargs.pop("op_id", None) or op_id or f"{op_type.lower()}_{uuid.uuid4().hex[:8]}"
            try:
                result = await fn(*args, **kwargs)
                status = "FIRED"
                err = None
            except Exception as exc:
                result = None
                status = "ERROR"
                err = str(exc)
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                _build_span(trace, resolved_id, resolved_parents, elapsed, result, status, err, kwargs)
            return result

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            trace = _current_trace.get()
            start = time.perf_counter()
            resolved_parents = kwargs.pop("parent_ids", None) or parent_ids or (
                [trace.spans[-1].op_id] if trace and trace.spans else []
            )
            resolved_id = kwargs.pop("op_id", None) or op_id or f"{op_type.lower()}_{uuid.uuid4().hex[:8]}"
            try:
                result = fn(*args, **kwargs)
                status = "FIRED"
                err = None
            except Exception as exc:
                result = None
                status = "ERROR"
                err = str(exc)
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                _build_span(trace, resolved_id, resolved_parents, elapsed, result, status, err, kwargs)
            return result

        return async_wrapper if iscoroutinefunction(fn) else sync_wrapper

    return decorator


class observe_gate:
    def __init__(self, gate_name: str, fired: bool, gate_values: Dict[str, Any] | None = None):
        self.gate_name = gate_name
        self.fired = fired
        self.gate_values = gate_values or {}
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        trace = _current_trace.get()
        if trace is None:
            return
        elapsed = (time.perf_counter() - self._start) * 1000
        trace.spans.append(
            OperatorSpan(
                op_id=f"gate_{uuid.uuid4().hex[:8]}",
                op_type="GATE",
                op_name=self.gate_name,
                parent_ids=[trace.spans[-1].op_id] if trace.spans else [],
                status="FIRED" if self.fired else "SKIPPED_BY_GATE",
                deterministic=True,
                replay_policy="NOT_REPLAYABLE",
                latency_ms=elapsed,
                gate_values=self.gate_values,
            )
        )


async def push_trace(trace: RetrievalTraceV2, endpoint: str, timeout: float = 5.0) -> Dict[str, Any]:
    payload = trace.to_dict()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        return response.json() if response.content else {"stored": True}
