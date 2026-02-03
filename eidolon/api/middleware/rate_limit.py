from __future__ import annotations

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class SlidingWindowLimiter:
    def __init__(self, capacity: int, window_seconds: int) -> None:
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.buckets: dict[str, tuple[int, float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        count, reset = self.buckets.get(key, (0, now + self.window_seconds))
        if now > reset:
            count = 0
            reset = now + self.window_seconds
        if count >= self.capacity:
            self.buckets[key] = (count, reset)
            return False
        self.buckets[key] = (count + 1, reset)
        return True

    def reset_at(self, key: str) -> float:
        return self.buckets.get(key, (0, time.time() + self.window_seconds))[1]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple per-identity sliding window limiter for API routes.
    Replace with Redis-backed limiter in production.
    """

    def __init__(self, app, capacity: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limiter = SlidingWindowLimiter(capacity, window_seconds)

    async def dispatch(self, request: Request, call_next):
        identity = getattr(request.state, "identity", None)
        key = identity.user_id if identity else request.client.host
        if not self.limiter.allow(key):
            reset_at = self.limiter.reset_at(key)
            retry_after = max(1, int(reset_at - time.time()))
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
