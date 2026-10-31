"""Tests for GET /api/u/{username}."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


PROFILE_ROW = {
    "user_id": "user-1",
    "username": "alice",
    "display_name": "Alice",
    "avatar_url": None,
    "bio": None,
    "is_public": True,
}


class TestGetPublicProfile:
    @patch("app.public.profiles.get_admin_client")
    def test_public_profile_zero_shares_returns_200(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[PROFILE_ROW])
        )
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )

        resp = client.get("/api/u/alice")

        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "alice"
        assert body["share_count"] == 0

    @patch("app.public.profiles.get_admin_client")
    def test_public_profile_not_found_returns_404(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )

        resp = client.get("/api/u/nobody")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Profile not found"
