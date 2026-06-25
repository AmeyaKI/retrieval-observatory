from __future__ import annotations

from typing import Callable, Iterable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from retrieval_observatory.tracing.recorder import TraceRecorder, _TraceContext

# Infrastructure routes that are not retrieval queries — excluded by default so traces
# (and failure signals like empty_candidates) are not polluted with docs/health noise.
DEFAULT_EXCLUDE_PATHS = ("/docs", "/openapi.json", "/redoc", "/health", "/favicon.ico")


def get_trace(request: Request) -> Optional[_TraceContext]:
    """Return the active trace context for this request, if any."""
    return getattr(request.state, "retobs_trace", None)


def _default_query_extractor(request: Request) -> str:
    """Capture the real search query when present, else fall back to the path."""
    q = request.query_params.get("q")
    if q:
        return q
    path = request.url.path
    return f"{path}?{request.query_params}" if request.query_params else path


class RetrievalTracingMiddleware(BaseHTTPMiddleware):
    """Record one TraceLens trace per HTTP request (excluding infra routes)."""

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


def instrument_fastapi(
    app,
    recorder: TraceRecorder,
    pipeline_id: str = "default",
    *,
    exclude_paths: Iterable[str] = DEFAULT_EXCLUDE_PATHS,
    query_extractor: Callable[[Request], str] = _default_query_extractor,
) -> None:
    """Install RetrievalTracingMiddleware on a FastAPI/Starlette app.

    ``exclude_paths`` skips infra routes (defaults cover /docs, /openapi.json, etc.).
    ``query_extractor`` controls what is stored as the trace's query_text; the default
    reads the ``q`` query parameter and falls back to the request path.
    """
    app.add_middleware(
        RetrievalTracingMiddleware,
        recorder=recorder,
        pipeline_id=pipeline_id,
        exclude_paths=exclude_paths,
        query_extractor=query_extractor,
    )
