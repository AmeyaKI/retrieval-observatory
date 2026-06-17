from __future__ import annotations

from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from retrieval_observatory.tracing.recorder import TraceRecorder, _TraceContext


def get_trace(request: Request) -> Optional[_TraceContext]:
    """Return the active trace context for this request, if any."""
    return getattr(request.state, "retobs_trace", None)


class RetrievalTracingMiddleware(BaseHTTPMiddleware):
    """Record one TraceLens trace per HTTP request."""

    def __init__(self, app, recorder: TraceRecorder, pipeline_id: str = "default"):
        super().__init__(app)
        self.recorder = recorder
        self.pipeline_id = pipeline_id

    async def dispatch(self, request: Request, call_next) -> Response:
        query_text = request.url.path
        if request.query_params:
            query_text = f"{query_text}?{request.query_params}"
        ctx = self.recorder.start_trace(query_text=query_text, pipeline_id=self.pipeline_id)
        request.state.retobs_trace = ctx
        try:
            response = await call_next(request)
            status = "ERROR" if response.status_code >= 500 else "OK"
            await self.recorder.finish_trace(ctx, status=status)
            return response
        except Exception as exc:
            await self.recorder.finish_trace(ctx, status="ERROR", error=exc)
            raise


def instrument_fastapi(app, recorder: TraceRecorder, pipeline_id: str = "default") -> None:
    """Install RetrievalTracingMiddleware on a FastAPI/Starlette app."""
    app.add_middleware(RetrievalTracingMiddleware, recorder=recorder, pipeline_id=pipeline_id)
