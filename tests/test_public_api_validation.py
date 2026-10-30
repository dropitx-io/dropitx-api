"""Tests for public API 422 validation errors.

Endpoints that return 422 when called without required fields.
No Supabase connection needed — Pydantic validation runs before the handler.

8 PUBLIC endpoints returning 422 without required fields:
  1. POST /api/shares/{slug}/unlock     — body.password (str, min 1)
  2. POST /api/analytics/track          — body.slug
  3. POST /api/shares/{slug}/comments   — body.author_name, body.content
  4. POST /api/upload                   — multipart file
  5. POST /api/upload/batch             — multipart files
  6. GET  /api/search                   — query.q (str, min 2)
  7. GET  /api/oembed                   — query.url (str)
  8. POST /api/shares/{slug}/set-password — body when no delete_token and no JWT
      (returns 401 first — see TestAuthRequiredEndpoints)

3 additional endpoints return 401 BEFORE body validation (JWT required):
  POST /api/publish, PUT /api/publish/{slug}, POST /api/images/upload
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _client():
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )


def _assert_422(resp, missing_fields: list[str]):
    """Assert a 422 response with Pydantic-style validation errors."""
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["detail"] is not None
    errors = body["detail"]
    assert isinstance(errors, list)
    reported_fields = set()
    for err in errors:
        loc = err.get("loc", [])
        if len(loc) >= 2:
            reported_fields.add(loc[-1])
    for field in missing_fields:
        assert field in reported_fields, (
            f"Expected validation error for '{field}' but got errors for: {reported_fields}"
        )


# ---------------------------------------------------------------------------
# 1. POST /api/shares/{slug}/unlock
#    Required: body.password (str, min_length=1)
# ---------------------------------------------------------------------------

class TestShareUnlock:
    async def test_422_without_password(self):
        async with await _client() as c:
            resp = await c.post("/api/shares/abc123/unlock", json={})
        _assert_422(resp, ["password"])

    async def test_422_with_empty_password(self):
        async with await _client() as c:
            resp = await c.post("/api/shares/abc123/unlock", json={"password": ""})
        _assert_422(resp, ["password"])

    async def test_422_without_body(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/unlock",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 422

    async def test_valid_body_passes_validation(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/unlock",
                json={"password": "secret123"},
            )
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# 2. POST /api/analytics/track
#    Required: body.slug (str, 1-200)
# ---------------------------------------------------------------------------

class TestAnalyticsTrack:
    async def test_422_without_fields(self):
        async with await _client() as c:
            resp = await c.post("/api/analytics/track", json={})
        _assert_422(resp, ["slug"])

    async def test_422_empty_slug(self):
        async with await _client() as c:
            resp = await c.post("/api/analytics/track", json={"slug": ""})
        _assert_422(resp, ["slug"])

    async def test_valid_body_passes_validation(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/analytics/track",
                json={"slug": "abc123", "referrer": "https://example.org", "is_embed": True},
            )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# 3. POST /api/shares/{slug}/comments
#    Required: body.author_name (str, 1-100), body.content (str, 1-5000)
# ---------------------------------------------------------------------------

class TestShareComments:
    async def test_422_without_fields(self):
        async with await _client() as c:
            resp = await c.post("/api/shares/abc123/comments", json={})
        _assert_422(resp, ["author_name", "content"])

    async def test_422_missing_content(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/comments",
                json={"author_name": "John"},
            )
        _assert_422(resp, ["content"])

    async def test_422_missing_author_name(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/comments",
                json={"content": "Great share!"},
            )
        _assert_422(resp, ["author_name"])

    async def test_422_empty_fields(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/comments",
                json={"author_name": "", "content": ""},
            )
        _assert_422(resp, ["author_name", "content"])

    async def test_valid_body_passes_validation(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/comments",
                json={"author_name": "John", "content": "Great share!"},
            )
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# 4. POST /api/upload
#    Required: file (UploadFile — multipart/form-data)
# ---------------------------------------------------------------------------

class TestUpload:
    async def test_422_without_file(self):
        async with await _client() as c:
            resp = await c.post("/api/upload")
        assert resp.status_code == 422

    async def test_422_with_empty_form(self):
        async with await _client() as c:
            resp = await c.post("/api/upload", data={"some_field": "value"})
        assert resp.status_code == 422

    async def test_valid_file_passes_validation(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/upload",
                files={"file": ("test.html", b"<h1>Hello</h1>", "text/html")},
            )
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# 5. POST /api/upload/batch
#    Required: files (list of UploadFile — multipart/form-data)
# ---------------------------------------------------------------------------

class TestUploadBatch:
    async def test_422_without_files(self):
        async with await _client() as c:
            resp = await c.post("/api/upload/batch")
        assert resp.status_code == 422

    async def test_valid_files_passes_validation(self):
        async with await _client() as c:
            resp = await c.post(
                "/api/upload/batch",
                files=[
                    ("files", ("a.html", b"<h1>A</h1>", "text/html")),
                    ("files", ("b.html", b"<h1>B</h1>", "text/html")),
                ],
            )
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# 6. GET /api/search
#    Required: query.q (str, min_length=2)
# ---------------------------------------------------------------------------

class TestSearch:
    async def test_422_without_query(self):
        async with await _client() as c:
            resp = await c.get("/api/search")
        _assert_422(resp, ["q"])

    async def test_422_with_short_query(self):
        async with await _client() as c:
            resp = await c.get("/api/search?q=a")
        _assert_422(resp, ["q"])

    async def test_valid_query_passes_validation(self):
        async with await _client() as c:
            resp = await c.get("/api/search?q=hello")
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# 7. GET /api/oembed
#    Required: query.url (str)
# ---------------------------------------------------------------------------

class TestOembed:
    async def test_422_without_url(self):
        async with await _client() as c:
            resp = await c.get("/api/oembed")
        _assert_422(resp, ["url"])

    async def test_valid_url_passes_validation(self):
        async with await _client() as c:
            resp = await c.get("/api/oembed?url=https://dropitx.com/s/abc123")
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# 8. POST /api/shares/{slug}/set-password
#    Required: at least delete_token OR authenticated user (JWT)
#    Body: SetPasswordRequest — password (optional), delete_token (optional)
#    Without JWT and without delete_token → 401 (auth runs first)
#    With delete_token but no password → NOT 422 (both fields optional)
# ---------------------------------------------------------------------------

class TestSetPassword:
    async def test_401_without_auth_and_no_delete_token(self):
        """No JWT + no delete_token → 401 before any body validation."""
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/set-password",
                json={"password": "newpass"},
            )
        assert resp.status_code == 401

    async def test_valid_body_passes_validation(self):
        """With delete_token, body is valid (password is optional).
        Won't be 422 — will be 404/500 without DB."""
        async with await _client() as c:
            resp = await c.post(
                "/api/shares/abc123/set-password",
                json={"password": "newpass", "delete_token": "tok_abc"},
            )
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# Auth-required endpoints (return 401 before 422)
# These are NOT counted in the "8 public API 422" list because auth
# intercepts the request before body validation runs.
# ---------------------------------------------------------------------------

class TestAuthRequiredEndpoints:
    """Endpoints that require JWT — return 401, not 422, when called publicly."""

    async def test_publish_returns_401_not_422(self):
        async with await _client() as c:
            resp = await c.post("/api/publish", json={})
        assert resp.status_code == 401

    async def test_update_publish_returns_401_not_422(self):
        async with await _client() as c:
            resp = await c.put("/api/publish/abc123", json={})
        assert resp.status_code == 401

    async def test_image_upload_returns_401_not_422(self):
        async with await _client() as c:
            resp = await c.post("/api/images/upload")
        assert resp.status_code == 401

    async def test_versions_list_returns_401_not_422(self):
        async with await _client() as c:
            resp = await c.get("/api/shares/abc123/versions")
        assert resp.status_code == 401

    async def test_version_detail_returns_401_not_422(self):
        async with await _client() as c:
            resp = await c.get("/api/shares/abc123/versions/1")
        assert resp.status_code == 401

    async def test_version_restore_returns_401_not_422(self):
        async with await _client() as c:
            resp = await c.post("/api/shares/abc123/versions/1/restore")
        assert resp.status_code == 401
