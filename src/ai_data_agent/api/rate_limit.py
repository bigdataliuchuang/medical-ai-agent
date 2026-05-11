"""In-memory token bucket rate limiter."""

from __future__ import annotations

import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class RateLimiter:
    """Token bucket rate limiter keyed by API key or IP."""

    def __init__(self, requests_per_minute: int = 30, burst: int = 10):
        self._rpm = requests_per_minute
        self._burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refill)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(self._burst), now))
        elapsed = now - last
        refill = elapsed * (self._rpm / 60.0)
        tokens = min(self._burst, tokens + refill)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1, now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting."""

    def __init__(self, app, requests_per_minute: int = 30, burst: int = 10):
        super().__init__(app)
        self._limiter = RateLimiter(requests_per_minute, burst)

    async def dispatch(self, request: Request, call_next) -> Response:
        key = request.headers.get("X-API-Key") or request.client.host or "anonymous"
        if not self._limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        return await call_next(request)
