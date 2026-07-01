from __future__ import annotations

from typing import Callable, Iterable, Optional, Union

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from retrieval_observatory.tracing.recorder import TraceRecorder, TraceRecorderV2, _TraceContext, _TraceContextV2

DEFAULT_EXCLUDE_PATHS = ("/docs", "/openapi.json", "/redoc", "/health", "/favicon.ico")


def get_trace(request: Request) -> Optional[Union[_TraceContext, _TraceContextV2]]:
    """Return the active trace context for this request, if any."""
    return getattr(request.state, "retobs_trace", None)


def _default_query_extractor(request: Request) -> str:
    """Capture the real search query when present, else fall back to the path."""
    q = request.query_params.get("q")
    if q:
        return q
    path = request.url.path
    return f"{path}?{request.query_params}" if request.query_params else path


# ---------------------------------------------------------------------------
# Legacy (V1) middleware — kept for backward compatibility
# ---------------------------------------------------------------------------

class RetrievalTracingMiddleware(BaseHTTPMiddleware):
    """Record one TraceLens trace per HTTP request (excluding infra routes).

    .. deprecated:: Phase 5
        Prefer ``RetrievalTracingMiddlewareV2`` for new code.
    """

    def __init__(
        self,
        app,
        recorder: TraceRecorder,
        pipeline_id: str = "default",
        *,
        exclude_paths: Iterable[str] = DEFAULT_EXCLUDE_PATHS,
        query_extractor: Callable[[Request], str] = _default_query_extractor,
    ):
        super().__init__(app)
        self.recorder = recorder
        self.pipeline_id = pipeline_id
        self.exclude_paths = tuple(exclude_paths)
        self.query_extractor = query_extractor

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)
        query_text = self.query_extractor(request)
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


# ---------------------------------------------------------------------------
# V2 middleware — builds RetrievalTraceV2 objects
# ---------------------------------------------------------------------------

class RetrievalTracingMiddlewareV2(BaseHTTPMiddleware):
    """Record one V2 trace per HTTP request (excluding infra routes)."""

    def __init__(
        self,
        app,
        recorder: TraceRecorderV2,
        pipeline_id: str = "default",
        *,
        exclude_paths: Iterable[str] = DEFAULT_EXCLUDE_PATHS,
        query_extractor: Callable[[Request], str] = _default_query_extractor,
    ):
        super().__init__(app)
        self.recorder = recorder
        self.pipeline_id = pipeline_id
        self.exclude_paths = tuple(exclude_paths)
        self.query_extractor = query_extractor

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)
        query_text = self.query_extractor(request)
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


def instrument_fastapi(
    app,
    recorder: Union[TraceRecorder, TraceRecorderV2],
    pipeline_id: str = "default",
    *,
    exclude_paths: Iterable[str] = DEFAULT_EXCLUDE_PATHS,
    query_extractor: Callable[[Request], str] = _default_query_extractor,
) -> None:
    """Install retrieval tracing middleware on a FastAPI/Starlette app.

    Accepts either a V1 ``TraceRecorder`` or a V2 ``TraceRecorderV2`` and selects
    the corresponding middleware automatically.
    """
    if isinstance(recorder, TraceRecorderV2):
        app.add_middleware(
            RetrievalTracingMiddlewareV2,
            recorder=recorder,
            pipeline_id=pipeline_id,
            exclude_paths=exclude_paths,
            query_extractor=query_extractor,
        )
    else:
        app.add_middleware(
            RetrievalTracingMiddleware,
            recorder=recorder,
            pipeline_id=pipeline_id,
            exclude_paths=exclude_paths,
            query_extractor=query_extractor,
        )
