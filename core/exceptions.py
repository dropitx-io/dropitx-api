"""Custom exceptions and standard error-response model."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Uniform error envelope returned by all exception handlers."""

    error: str
    detail: str | None = None
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """Raised when a rate limit is exceeded."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after


class ShareNotFoundError(Exception):
    """Raised when a requested share slug does not exist."""


class SharePasswordRequired(Exception):
    """Raised when a password-protected share has not been unlocked yet."""
