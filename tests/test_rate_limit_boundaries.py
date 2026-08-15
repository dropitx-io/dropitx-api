"""Boundary tests for core/rate_limit.py against a live local Postgres.

Requires `docker compose up -d` — these tests call the real Supabase-style
RPC `check_rate_limit` directly, no HTTP layer involved.
"""

from __future__ import annotations

import uuid

from core.rate_limit import (
    check_password_rate_limit,
    check_bulk_download_rate_limit,
)


def _fresh_ip_slug() -> tuple[str, str]:
    token = uuid.uuid4().hex
    return f"203.0.113.{int(token[:2], 16) % 255}-{token}", f"slug-{token}"


def _fresh_ip() -> str:
    token = uuid.uuid4().hex
    return f"198.51.100.{int(token[:2], 16) % 255}-{token}"


class TestPasswordRateLimitBoundary:
    def test_nth_succeeds_and_n_plus_1th_rejected(self):
        ip, slug = _fresh_ip_slug()

        for attempt in range(1, 6):
            result = check_password_rate_limit(ip, slug)
            assert result.success is True, f"attempt {attempt} should succeed"

        sixth = check_password_rate_limit(ip, slug)
        assert sixth.success is False


class TestBulkDownloadRateLimitBoundary:
    def test_nth_succeeds_and_n_plus_1th_rejected(self):
        ip = _fresh_ip()

        for attempt in range(1, 11):
            result = check_bulk_download_rate_limit(ip)
            assert result.success is True, f"attempt {attempt} should succeed"

        eleventh = check_bulk_download_rate_limit(ip)
        assert eleventh.success is False
