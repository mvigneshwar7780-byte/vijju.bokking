"""Cross-cutting HTTP middleware: request ids, access logs, naive rate limits."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.errors import RateLimitedError
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)

RequestIdHeader = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign (or adopt) a request id and emit one structured access log line."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get(RequestIdHeader) or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            request_id_ctx.reset(token)
        response.headers[RequestIdHeader] = rid
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms}"
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
            request_id=rid,
        )
        return response


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """A deliberately simple sliding-window limiter.

    In-process and per-worker, so it is *not* a production rate limiter -- it is
    here so the API surface (429 + ``Retry-After``) and the client handling of it
    exist from day one. Swap the backing store for Redis when you scale out;
    nothing outside this class needs to change.
    """

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _limit_for(self, path: str) -> int:
        if "/ai/" in path:
            return settings.rate_limit_ai_per_minute
        return settings.rate_limit_default_per_minute

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        bucket_key = f"{client}:{'ai' if '/ai/' in request.url.path else 'default'}"
        limit = self._limit_for(request.url.path)

        now = time.monotonic()
        window = self._hits[bucket_key]
        while window and now - window[0] > 60.0:
            window.popleft()

        if len(window) >= limit:
            err = RateLimitedError(
                details={"limit_per_minute": limit, "scope": bucket_key.split(":")[-1]}
            )
            return JSONResponse(
                status_code=err.status_code,
                content=err.to_payload(),
                headers={"Retry-After": "60"},
            )

        window.append(now)
        return await call_next(request)


def register_middleware(app: FastAPI) -> None:
    # Order matters: the last one added is the outermost. Request ids must wrap
    # everything so even a rate-limit rejection carries one.
    app.add_middleware(InMemoryRateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[RequestIdHeader, "Server-Timing"],
    )
    app.add_middleware(RequestContextMiddleware)
