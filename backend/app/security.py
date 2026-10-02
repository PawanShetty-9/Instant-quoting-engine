"""API-key auth for integration endpoints, rate limiting and HTTP hardening."""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import Settings, get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Depends(_api_key_header), settings: Settings = Depends(get_settings)) -> None:
    expected = settings.admin_api_key.get_secret_value() if settings.admin_api_key else None
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "integration API disabled (QUOTE_ADMIN_API_KEY not set)"
        )
    if not api_key or not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid or missing X-API-Key", headers={"WWW-Authenticate": "ApiKey"}
        )


class SlidingWindowRateLimiter:
    """In-process limiter keyed by client IP. Use a shared store (Redis) when running >1 replica."""

    def __init__(self, limit: int, window_s: int) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int | None:
        """Register a hit. Returns seconds to wait if the limit is exceeded, else None."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return int(self.window_s - (now - hits[0])) + 1
            hits.append(now)
            if len(self._hits) > 50_000:  # bound memory under address-spraying
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] <= self.window_s}
            return None


def client_ip(request: Request) -> str:
    """Caller's IP for rate limits and guest quotas.

    Behind N reverse proxies (QUOTE_TRUSTED_PROXY_HOPS), the real client is the N-th
    X-Forwarded-For entry from the right: every proxy appends what it saw, so entries
    further left are client-supplied and could be forged to dodge limits.
    """
    hops = request.app.state.settings.trusted_proxy_hops
    if hops > 0:
        chain = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id[:64]
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response
