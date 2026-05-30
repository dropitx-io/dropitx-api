"""Request tracking, timing, and security-header middleware."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.logging_config import request_id_var

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request Tracking Middleware
# ---------------------------------------------------------------------------

class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID and log method, path, status, and latency."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Reuse client-supplied ID or mint a new one
        req_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(req_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.error("Unhandled exception in %s %s", request.method, request.url.path, exc_info=True)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Structured request log
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "")
        )
        logger.info(
            "%s %s → %s (%sms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
            },
        )

        # Echo tracking info back to clients / CDNs
        response.headers["x-request-id"] = req_id
        response.headers["x-response-time"] = f"{duration_ms}ms"

        return response


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    _HEADERS: dict[str, str] = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "x-xss-protection": "1; mode=block",
        "referrer-policy": "strict-origin-when-cross-origin",
        "permissions-policy": "camera=(), microphone=(), geolocation=()",
        "strict-transport-security": "max-age=31536000; includeSubDomains",
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in self._HEADERS.items():
            response.headers[key] = value
        return response
