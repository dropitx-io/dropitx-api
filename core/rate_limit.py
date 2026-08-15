"""Rate limiting via Supabase Postgres RPC 'check_rate_limit'."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from core.supabase import get_admin_client

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    success: bool
    limit: int
    remaining: int
    reset: int  # Unix timestamp


def _parse_reset(value) -> int:
    """Convert reset_at from RPC to unix epoch. Handles int or ISO string."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def _check_rpc(
    key: str,
    max_attempts: int,
    window_secs: int,
    *,
    fail_open: bool,
) -> RateLimitResult:
    """Call Supabase RPC check_rate_limit and return structured result.

    fail_open=True  -> return success=True on DB error.
    fail_open=False -> return success=False on DB error.
    """
    default = RateLimitResult(
        success=fail_open,
        limit=max_attempts,
        remaining=max_attempts,
        reset=0,
    )
    try:
        client = get_admin_client()
        resp = client.rpc(
            "check_rate_limit",
            {
                "p_key": key,
                "p_max_attempts": max_attempts,
                "p_window_secs": window_secs,
            },
        ).execute()

        rows = resp.data or []
        if not rows:
            return default

        row = rows[0]
        return RateLimitResult(
            success=bool(row.get("success", fail_open)),
            limit=max_attempts,
            remaining=int(row.get("remaining", max_attempts)),
            reset=_parse_reset(row.get("reset_at", 0)),
        )

    except Exception:
        logger.warning("Rate limit RPC failed for key=%s", key, exc_info=True)
        return default


def check_upload_rate_limit(ip: str) -> RateLimitResult:
    """10 uploads per minute per IP. Fail-open."""
    return _check_rpc(f"upload:{ip}", max_attempts=10, window_secs=60, fail_open=True)


def check_password_rate_limit(ip: str, slug: str) -> RateLimitResult:
    """5 attempts per 10 minutes per IP+slug. Fail-closed."""
    return _check_rpc(f"pwd:{ip}:{slug}", max_attempts=5, window_secs=600, fail_open=False)


def check_oembed_rate_limit(ip: str) -> RateLimitResult:
    """60 oEmbed requests per minute per IP. Fail-open."""
    return _check_rpc(f"oembed:{ip}", max_attempts=60, window_secs=60, fail_open=True)


def check_bulk_download_rate_limit(ip: str) -> RateLimitResult:
    """10 bulk-download requests per minute per IP. Fail-open."""
    return _check_rpc(f"bulkdl:{ip}", max_attempts=10, window_secs=60, fail_open=True)


def check_public_read_rate_limit(ip: str) -> RateLimitResult:
    """60 public share reads (content/download/preview) per minute per IP. Fail-open."""
    return _check_rpc(f"read:{ip}", max_attempts=60, window_secs=60, fail_open=True)


def check_analytics_rate_limit(ip: str) -> bool:
    """60 analytics requests per minute per IP. Fail-open. Returns bool."""
    result = _check_rpc(f"analytics:{ip}", max_attempts=60, window_secs=60, fail_open=True)
    return result.success
