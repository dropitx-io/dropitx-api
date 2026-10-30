"""Automated test for all DropItX API endpoints.

Tests endpoint existence and basic response codes WITHOUT a live Supabase connection.
Uses ASGI transport to test FastAPI app directly.

52 API endpoints (excluding /docs, /redoc, /openapi.json, /health, /health/deep):

PUBLIC (no auth):
  1.  GET    /health
  2.  GET    /health/deep
  3.  GET    /api/search
  4.  GET    /api/oembed
  5.  POST   /api/analytics/track
  6.  GET    /api/shares/{slug}/content
  7.  GET    /api/shares/{slug}/comments
  8.  POST   /api/shares/{slug}/comments
  9.  GET    /api/shares/{slug}/versions
  10. GET    /api/shares/{slug}/versions/{version_num}
  11. GET    /api/qr/{slug}
  12. GET    /api/shares/{slug}/download
  13. GET    /api/shares/{slug}/preview
  14. GET    /api/shares/{slug}/download-status
  15. GET    /api/shares/{slug}/files

OPTIONAL AUTH:
  14. POST   /api/upload
  15. POST   /api/upload/batch
  16. POST   /api/upload/multi
  17. DELETE /api/shares/{slug}
  18. POST   /api/shares/{slug}/set-password
  19. POST   /api/shares/{slug}/unlock
  20. POST   /api/shares/{slug}/burn

JWT REQUIRED:
  21. POST   /api/publish
  22. PUT    /api/publish/{slug}
  23. POST   /api/images/upload
  24. GET    /api/dashboard/teams
  25. POST   /api/dashboard/teams
  26. GET    /api/dashboard/teams/{slug}
  27. PATCH  /api/dashboard/teams/{slug}
  28. DELETE /api/dashboard/teams/{slug}
  29. GET    /api/dashboard/teams/{slug}/members
  30. PATCH  /api/dashboard/teams/{slug}/members
  31. DELETE /api/dashboard/teams/{slug}/members
  32. GET    /api/dashboard/teams/{slug}/invites
  33. POST   /api/dashboard/teams/{slug}/invites
  34. DELETE /api/dashboard/teams/{slug}/invites
  35. POST   /api/dashboard/teams/{slug}/invites/bulk
  36. POST   /api/dashboard/teams/{slug}/invites/{invite_id}/resend
  37. GET    /api/dashboard/teams/{slug}/events
  38. GET    /api/dashboard/teams/{slug}/shares
  39. GET    /api/dashboard/invitations
  40. POST   /api/invite/accept
  41. POST   /api/invite/decline
  42. GET    /api/download/group/{slug}

API KEY REQUIRED:
  43. POST   /api/v1/documents
  44. GET    /api/v1/documents
  45. GET    /api/v1/documents/{slug}
  46. PATCH  /api/v1/documents/{slug}
  47. DELETE /api/v1/documents/{slug}
  48. GET    /api/v1/documents/{slug}/revisions
  49. GET    /api/v1/documents/{slug}/revisions/{revision}
  50. POST   /api/v1/documents/{slug}/revisions/{revision}/restore
  51. POST   /api/v1/keys
  52. GET    /api/v1/keys
  53. DELETE /api/v1/keys/{key_id}
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


FAKE_SLUG = "test-slug-abc123"
FAKE_TOKEN = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.fake"
FAKE_API_KEY = "shk_fakeapikey123456789"


# ---------------------------------------------------------------------------
# 1. Health endpoints (no auth, no Supabase needed for basic)
# ---------------------------------------------------------------------------

class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_deep(self, client):
        """Deep health may fail if Supabase is not running — that's OK."""
        resp = await client.get("/health/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data


# ---------------------------------------------------------------------------
# 2. Public endpoints (no auth)
# ---------------------------------------------------------------------------

class TestPublicEndpoints:
    @pytest.mark.asyncio
    async def test_search_missing_q(self, client):
        resp = await client.get("/api/search")
        assert resp.status_code == 422  # q required

    @pytest.mark.asyncio
    async def test_search_with_q(self, client):
        resp = await client.get("/api/search", params={"q": "test query"})
        # May return 200 with empty results or 500 if Supabase is down
        assert resp.status_code in (200, 500)

    @pytest.mark.asyncio
    async def test_oembed_missing_url(self, client):
        resp = await client.get("/api/oembed")
        assert resp.status_code == 422  # url required

    @pytest.mark.asyncio
    async def test_oembed_with_url(self, client):
        resp = await client.get("/api/oembed", params={"url": "https://dropitx.com/s/test"})
        assert resp.status_code in (200, 404, 500)

    @pytest.mark.asyncio
    async def test_analytics_track_missing_body(self, client):
        resp = await client.post("/api/analytics/track", json={})
        assert resp.status_code == 422  # slug required

    @pytest.mark.asyncio
    async def test_analytics_track_valid(self, client):
        resp = await client.post("/api/analytics/track", json={"slug": FAKE_SLUG})
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_share_content_not_found(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/content")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_comments_not_found(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/comments")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_comments_post_not_found(self, client):
        resp = await client.post(f"/api/shares/{FAKE_SLUG}/comments", json={
            "author_name": "Test",
            "content": "Test comment",
        })
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_versions_requires_auth(self, client):
        """Versions endpoints require JWT (not public despite /shares/ prefix)."""
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/versions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_share_version_detail_requires_auth(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/versions/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_qrcode_not_found(self, client):
        resp = await client.get(f"/api/qr/{FAKE_SLUG}")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_download_not_found(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/download")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_preview_not_found(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/preview")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_download_status_not_found(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/download-status")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_share_files_not_found(self, client):
        resp = await client.get(f"/api/shares/{FAKE_SLUG}/files")
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_public_profile_not_found(self, client):
        resp = await client.get(f"/api/u/{FAKE_SLUG}")
        assert resp.status_code in (404, 500)


# ---------------------------------------------------------------------------
# 3. Optional auth endpoints
# ---------------------------------------------------------------------------

class TestOptionalAuthEndpoints:
    @pytest.mark.asyncio
    async def test_upload_no_file(self, client):
        resp = await client.post("/api/upload")
        assert resp.status_code == 422  # file required

    @pytest.mark.asyncio
    async def test_upload_batch_no_files(self, client):
        resp = await client.post("/api/upload/batch")
        assert resp.status_code == 422  # files required

    @pytest.mark.asyncio
    async def test_upload_multi_no_files(self, client):
        resp = await client.post("/api/upload/multi")
        assert resp.status_code == 422  # files required

    @pytest.mark.asyncio
    async def test_delete_share_no_auth(self, client):
        resp = await client.delete(f"/api/shares/{FAKE_SLUG}")
        assert resp.status_code in (401, 404, 500)

    @pytest.mark.asyncio
    async def test_set_password_no_auth(self, client):
        resp = await client.post(f"/api/shares/{FAKE_SLUG}/set-password", json={
            "password": "test123",
        })
        assert resp.status_code in (401, 404, 500)

    @pytest.mark.asyncio
    async def test_unlock_share_missing_password(self, client):
        resp = await client.post(f"/api/shares/{FAKE_SLUG}/unlock", json={})
        assert resp.status_code == 422  # password required

    @pytest.mark.asyncio
    async def test_burn_share_no_auth(self, client):
        resp = await client.post(f"/api/shares/{FAKE_SLUG}/burn")
        assert resp.status_code in (401, 404, 500)

    @pytest.mark.asyncio
    @patch("app.public.encryption.get_admin_client")
    async def test_encrypt_share_no_auth(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )

        resp = await client.post(f"/api/shares/{FAKE_SLUG}/encrypt", json={
            "password": "test123",
        })
        assert resp.status_code in (401, 404, 500)

    @pytest.mark.asyncio
    @patch("app.public.encryption.get_admin_client")
    async def test_encrypt_share_empty_delete_token(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )

        resp = await client.post(f"/api/shares/{FAKE_SLUG}/encrypt", json={
            "password": "test123",
            "delete_token": "",
        })
        assert resp.status_code in (401, 404, 500)

    @pytest.mark.asyncio
    async def test_reencrypt_share_no_auth_or_rate_limited(self, client):
        resp = await client.post(f"/api/shares/{FAKE_SLUG}/reencrypt", json={
            "old_password": "test123",
            "new_password": "test456",
        })
        assert resp.status_code in (404, 500, 429)


# ---------------------------------------------------------------------------
# 4. JWT-required endpoints (should return 401 without valid JWT)
# ---------------------------------------------------------------------------

class TestJWTRequiredEndpoints:
    """All these endpoints require JWT auth. Without a valid token, expect 401."""

    @pytest.mark.asyncio
    async def test_publish_no_auth(self, client):
        resp = await client.post("/api/publish", json={
            "content": "<h1>Test</h1>",
            "title": "Test",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_publish_update_no_auth(self, client):
        resp = await client.put(f"/api/publish/{FAKE_SLUG}", json={
            "content": "<h1>Updated</h1>",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_images_upload_no_auth(self, client):
        resp = await client.post("/api/images/upload")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_teams_list_no_auth(self, client):
        resp = await client.get("/api/dashboard/teams")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_teams_create_no_auth(self, client):
        resp = await client.post("/api/dashboard/teams", json={"name": "Test Team"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_detail_no_auth(self, client):
        resp = await client.get(f"/api/dashboard/teams/{FAKE_SLUG}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_update_no_auth(self, client):
        resp = await client.patch(f"/api/dashboard/teams/{FAKE_SLUG}", json={"name": "Updated"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_delete_no_auth(self, client):
        resp = await client.delete(f"/api/dashboard/teams/{FAKE_SLUG}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_members_list_no_auth(self, client):
        resp = await client.get(f"/api/dashboard/teams/{FAKE_SLUG}/members")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_members_update_no_auth(self, client):
        resp = await client.patch(f"/api/dashboard/teams/{FAKE_SLUG}/members", json={})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_members_delete_no_auth(self, client):
        import json
        resp = await client.request("DELETE", f"/api/dashboard/teams/{FAKE_SLUG}/members",
                                    content=json.dumps({"user_id": "fake"}),
                                    headers={"content-type": "application/json"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_invites_list_no_auth(self, client):
        resp = await client.get(f"/api/dashboard/teams/{FAKE_SLUG}/invites")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_invites_create_no_auth(self, client):
        resp = await client.post(f"/api/dashboard/teams/{FAKE_SLUG}/invites", json={
            "email": "test@example.com",
            "role": "viewer",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_invites_delete_no_auth(self, client):
        import json
        resp = await client.request("DELETE", f"/api/dashboard/teams/{FAKE_SLUG}/invites",
                                    content=json.dumps({"invite_id": "fake"}),
                                    headers={"content-type": "application/json"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_invites_bulk_no_auth(self, client):
        resp = await client.post(f"/api/dashboard/teams/{FAKE_SLUG}/invites/bulk", json={
            "invites": [{"email": "test@example.com", "role": "viewer"}],
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_invite_resend_no_auth(self, client):
        resp = await client.post(f"/api/dashboard/teams/{FAKE_SLUG}/invites/inv123/resend")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_events_no_auth(self, client):
        resp = await client.get(f"/api/dashboard/teams/{FAKE_SLUG}/events")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_shares_no_auth(self, client):
        resp = await client.get(f"/api/dashboard/teams/{FAKE_SLUG}/shares")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invitations_list_no_auth(self, client):
        resp = await client.get("/api/dashboard/invitations")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invite_accept_no_auth(self, client):
        resp = await client.post("/api/invite/accept", json={"token": "fake"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invite_decline_no_auth(self, client):
        resp = await client.post("/api/invite/decline", json={"token": "fake"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_download_group_not_found(self, client):
        """Download group is public but returns 404 for unknown slugs."""
        resp = await client.get(f"/api/download/group/{FAKE_SLUG}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. API Key required endpoints (should return 401/403 without valid key)
# ---------------------------------------------------------------------------

class TestAPIKeyRequiredEndpoints:
    """V1 endpoints require API key auth. Without a valid key, expect 401/403."""

    @pytest.mark.asyncio
    async def test_v1_documents_create_no_auth(self, client):
        resp = await client.post("/api/v1/documents", json={
            "content": "<h1>Test</h1>",
            "title": "Test",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_documents_list_no_auth(self, client):
        resp = await client.get("/api/v1/documents")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_documents_get_no_auth(self, client):
        resp = await client.get(f"/api/v1/documents/{FAKE_SLUG}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_documents_update_no_auth(self, client):
        resp = await client.patch(f"/api/v1/documents/{FAKE_SLUG}", json={
            "content": "<h1>Updated</h1>",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_documents_delete_no_auth(self, client):
        resp = await client.delete(f"/api/v1/documents/{FAKE_SLUG}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_revisions_list_no_auth(self, client):
        resp = await client.get(f"/api/v1/documents/{FAKE_SLUG}/revisions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_revision_detail_no_auth(self, client):
        resp = await client.get(f"/api/v1/documents/{FAKE_SLUG}/revisions/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_revision_restore_no_auth(self, client):
        resp = await client.post(f"/api/v1/documents/{FAKE_SLUG}/revisions/1/restore")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_keys_create_no_auth(self, client):
        resp = await client.post("/api/v1/keys", json={"name": "Test Key"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_keys_list_no_auth(self, client):
        resp = await client.get("/api/v1/keys")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_v1_keys_revoke_no_auth(self, client):
        resp = await client.delete("/api/v1/keys/key123")
        assert resp.status_code == 401
