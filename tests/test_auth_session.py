"""Tests for GET /api/auth/session."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_firebase_claims


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("core.config.settings") as mock:
        mock.firebase_project_id = "test-project"
        mock.cors_origins = ["*"]
        yield mock


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def override_claims(claims):
    app.dependency_overrides[get_firebase_claims] = lambda: claims


PROFILE_ROW = {
    "user_id": "uid-1",
    "username": None,
    "display_name": None,
    "bio": None,
    "avatar_url": None,
    "is_public": False,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


class TestGetSession:
    def test_requires_auth(self, client):
        resp = client.get("/api/auth/session")
        assert resp.status_code == 401

    @patch("app.auth.session.get_admin_client")
    def test_provisions_and_returns_profile(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com", "email_verified": True})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[PROFILE_ROW])

        resp = client.get("/api/auth/session")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "uid-1"
        assert body["email"] == "a@b.com"
        assert body["email_verified"] is True
        assert body["profile"]["user_id"] == "uid-1"
        mock_client.rpc.assert_called_once_with(
            "provision_firebase_user", {"p_uid": "uid-1", "p_email": "a@b.com"}
        )

    @patch("app.auth.session.get_admin_client")
    def test_idempotent(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com"})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[PROFILE_ROW])

        r1 = client.get("/api/auth/session")
        r2 = client.get("/api/auth/session")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["profile"]["user_id"] == r2.json()["profile"]["user_id"]
        assert mock_client.rpc.call_count == 2

    @patch("app.auth.session.get_admin_client")
    def test_empty_profile_returns_500(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com"})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[])
        resp = client.get("/api/auth/session")
        assert resp.status_code == 500

    @patch("app.auth.session.get_admin_client")
    def test_rpc_exception_returns_500(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com"})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.side_effect = RuntimeError("db down")
        resp = client.get("/api/auth/session")
        assert resp.status_code == 500
