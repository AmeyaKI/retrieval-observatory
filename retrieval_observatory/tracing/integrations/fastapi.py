from contextlib import asynccontextmanager
from typing import Callable, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from retrieval_observatory.tracing.recorder import TraceContext, TraceRecorder

DEFAULT_EXCLUDE_PATHS = ("/docs", "/openapi.json", "/redoc", "/health", "/favicon.ico")


def get_trace(request: Request) -> TraceContext | None:
    return getattr(request.state, "retobs_trace", None)


def _default_query_extractor(request: Request) -> str:
    return request.query_params.get("q") or request.url.path


class RetrievalTracingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        recorder: TraceRecorder,
        pipeline_id: str,
        exclude_paths: Iterable[str],
        query_extractor: Callable[[Request], str],
    ):
        super().__init__(app)
        self.recorder, self.pipeline_id = recorder, pipeline_id
        self.exclude_paths, self.query_extractor = tuple(exclude_paths), query_extractor

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)
        try:
            context = self.recorder.start_trace(
                self.query_extractor(request), self.pipeline_id, request_id=request.headers.get("x-request-id")
            )
        except BaseException:
            self.recorder.sink.counters.serialization_failed()
            return await call_next(request)
        request.state.retobs_trace = context
        try:
            response = await call_next(request)
            self.recorder.finish(context, status="ERROR" if response.status_code >= 500 else "OK")
            return response
        except Exception as exc:
            self.recorder.finish(context, status="ERROR", error=exc)
            raise


def instrument_fastapi(
    app,
    recorder: TraceRecorder,
    pipeline_id: str = "default",
    *,
    excluded_paths: Iterable[str] = DEFAULT_EXCLUDE_PATHS,
    query_extractor: Callable[[Request], str] = _default_query_extractor,
) -> None:
    previous_lifespan = app.router.lifespan_context
    app.add_middleware(
        RetrievalTracingMiddleware,
        recorder=recorder,
        pipeline_id=pipeline_id,
        exclude_paths=excluded_paths,
        query_extractor=query_extractor,
    )

    @asynccontextmanager
    async def retobs_lifespan(_app):
        await recorder.sink.start()
        try:
            async with previous_lifespan(_app) as state:
                yield state
        finally:
            _app.state.retobs_shutdown = await recorder.sink.shutdown(recorder.sink.config.shutdown_timeout_s)
            store = getattr(recorder, "store", None)
            if store is not None:
                try:
                    await store.save_instrumentation_health(recorder.health())
                except BaseException:
                    recorder.sink.counters.permanent_failed()

    app.router.lifespan_context = retobs_lifespan
    app.state.retobs = recorder
