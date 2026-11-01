"""Every 429 tells the client how long to wait, in whole seconds, and the browser may read it.

RFC 9110 defines Retry-After as an HTTP-date or a non-negative integer of delay-seconds.
`RateLimitResult.reset` is the Unix time the window resets, so the header is the
distance to it, never the timestamp itself.
"""

from __future__ import annotations

import time
import uuid

import pytest

from core.rate_limit import RateLimitResult
from tests.conftest import act_as, unique_ip


def _limited(seconds_left: int) -> RateLimitResult:
    return RateLimitResult(success=False, limit=1, remaining=0, reset=int(time.time()) + seconds_left)


def _assert_delay_seconds(resp, upper: int) -> None:
    assert resp.status_code == 429, resp.text
    value = resp.headers.get("retry-after")
    assert value is not None and value.isdigit(), value
    assert 1 <= int(value) <= upper


_FILE = {"file": ("a.md", b"# a", "text/markdown")}

# (module whose limiter is patched, limiter name, method, path, request kwargs, needs a user)
_ENDPOINTS = [
    ("app.internal.upload", "check_upload_rate_limit", "post", "/api/upload", {"files": _FILE}, False),
    ("app.internal.upload", "check_upload_rate_limit", "post", "/api/upload/batch",
     {"files": [("files", ("a.md", b"# a", "text/markdown"))]}, False),
    ("app.internal.multi_upload", "check_upload_rate_limit", "post", "/api/upload/multi",
     {"files": [("files", ("a.md", b"# a", "text/markdown"))]}, False),
    ("app.internal.publish", "check_upload_rate_limit", "post", "/api/publish",
     {"json": {"content": "<p>x</p>"}}, True),
    ("app.internal.publish", "check_upload_rate_limit", "put", "/api/publish/any-slug",
     {"json": {"content": "<p>x</p>"}}, True),
    ("app.internal.cli_upload", "check_upload_rate_limit", "post", "/api/cli/upload", {"files": _FILE}, False),
    ("app.internal.cli_upload", "check_upload_rate_limit", "post", "/api/cli/upload/text",
     {"data": {"content": "hello"}}, False),
    ("app.public.comments", "check_upload_rate_limit", "post", "/api/shares/any-slug/comments",
     {"json": {"content": "hi"}}, False),
    ("app.public.file_requests", "check_upload_rate_limit", "post", "/api/requests/any-slug/upload",
     {"files": _FILE}, False),
    ("app.public.shares", "check_public_read_rate_limit", "get", "/api/shares/any-slug/content", {}, False),
    ("app.public.shares", "check_public_read_rate_limit", "get", "/api/shares/any-slug/download", {}, False),
    ("app.public.shares", "check_share_meta_rate_limit", "get", "/api/shares/any-slug", {}, False),
    ("app.internal.download", "check_bulk_download_rate_limit", "get", "/api/download/group/any-slug", {}, False),
]


@pytest.mark.parametrize(
    "module, limiter, method, path, kwargs, needs_user",
    _ENDPOINTS,
    ids=[f"{e[2].upper()} {e[3]}" for e in _ENDPOINTS],
)
def test_429_carries_retry_after_in_seconds_until_reset(
    client, seed, monkeypatch, module, limiter, method, path, kwargs, needs_user,
):
    act_as(seed.user() if needs_user else None)
    monkeypatch.setattr(f"{module}.{limiter}", lambda *args: _limited(42))

    resp = getattr(client, method)(path, headers=unique_ip(), **kwargs)

    _assert_delay_seconds(resp, 42)


def test_exhausted_password_bucket_reports_the_real_window(client, seed):
    """Live limiter: the sixth wrong password within 10 minutes waits at most 600 seconds."""
    share = seed.share(seed.user(), is_private=False)
    act_as(None)
    ip = {"cf-connecting-ip": f"10.9.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"}

    for _ in range(5):
        client.post(f"/api/shares/{share['slug']}/unlock", json={"password": "wrong"}, headers=ip)
    resp = client.post(f"/api/shares/{share['slug']}/unlock", json={"password": "wrong"}, headers=ip)

    _assert_delay_seconds(resp, 600)


def test_a_window_already_past_still_asks_for_one_second():
    assert RateLimitResult(success=False, limit=1, remaining=0, reset=0).retry_after == 1


def test_cors_exposes_retry_after_to_the_browser(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})

    exposed = {h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",")}
    assert "retry-after" in exposed
