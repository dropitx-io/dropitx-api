"""Tests for File Request Links endpoints."""

import io
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from app.dependencies import User, get_current_user


MOCK_SETTINGS = {
    "firebase_project_id": "test-project",
    "supabase_url": "https://test.supabase.co",
    "allowed_origins": "*",
    "frontend_url": "https://dropitx.com",
}


@pytest.fixture(autouse=True)
def mock_settings():
    """Mock settings to avoid .env requirement."""
    with patch("core.config.settings") as mock:
        for k, v in MOCK_SETTINGS.items():
            setattr(mock, k, v)
        mock.cors_origins = ["*"]
        yield mock


@pytest.fixture
def client():
    """Create test client."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_overrides(client):
    """Clean up dependency overrides after each test."""
    yield
    from app.main import app
    app.dependency_overrides.clear()


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return User(id="user-123", email="test@example.com")


def override_auth(user):
    """Override get_current_user dependency."""
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: user


def _make_file_request_row(**overrides):
    """Create a mock file_requests row."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "req-123",
        "slug": "testslug",
        "user_id": "user-123",
        "title": "Test Request",
        "description": None,
        "max_files": 10,
        "max_file_size_mb": 100,
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "require_name": False,
        "require_email": False,
        "is_active": True,
        "upload_count": 0,
        "total_size_bytes": 0,
        "created_at": now.isoformat(),
        **overrides,
    }
    return row


# =========================================================================
# POST /api/requests
# =========================================================================

class TestCreateFileRequest:

    def test_create_requires_auth(self, client):
        resp = client.post("/api/requests", json={"title": "Test"})
        assert resp.status_code == 401

    @patch("app.internal.file_requests.get_admin_client")
    def test_create_basic_request(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        now = datetime.now(timezone.utc)
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-new", "slug": "newslug", "created_at": now.isoformat()}]
        )

        resp = client.post("/api/requests", json={
            "title": "Submit deliverables",
            "description": "Upload your files",
            "max_files": 5,
            "max_file_size_mb": 50,
            "expires_in": "7d",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Submit deliverables"
        assert data["max_files"] == 5
        assert data["max_file_size_mb"] == 50
        assert data["is_active"] is True
        assert data["upload_count"] == 0
        assert "share_url" in data

    @patch("app.internal.file_requests.get_admin_client")
    def test_create_with_required_fields(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-req", "slug": "reqslug", "created_at": datetime.now(timezone.utc).isoformat()}]
        )

        resp = client.post("/api/requests", json={
            "title": "Job applications",
            "require_name": True,
            "require_email": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["require_name"] is True
        assert data["require_email"] is True

    @patch("app.internal.file_requests.get_admin_client")
    def test_create_defaults(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-def", "slug": "defslug", "created_at": datetime.now(timezone.utc).isoformat()}]
        )

        resp = client.post("/api/requests", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_files"] == 10
        assert data["max_file_size_mb"] == 100
        assert data["require_name"] is False

    @patch("app.internal.file_requests.get_admin_client")
    def test_create_invalid_expiration(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        resp = client.post("/api/requests", json={"expires_in": "invalid"})
        assert resp.status_code == 400

    @patch("app.internal.file_requests.get_admin_client")
    def test_create_custom_seconds(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-cs", "slug": "csslug", "created_at": datetime.now(timezone.utc).isoformat()}]
        )

        resp = client.post("/api/requests", json={"expires_in": "3600"})
        assert resp.status_code == 200


# =========================================================================
# GET /api/dashboard/requests
# =========================================================================

class TestListMyRequests:

    def test_list_requires_auth(self, client):
        resp = client.get("/api/dashboard/requests")
        assert resp.status_code == 401

    @patch("app.internal.file_requests.get_admin_client")
    def test_list_empty(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        resp = client.get("/api/dashboard/requests")
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("app.internal.file_requests.get_admin_client")
    def test_list_with_data(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(upload_count=3, total_size_bytes=1024000)]
        )

        resp = client.get("/api/dashboard/requests")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["upload_count"] == 3
        assert "share_url" in data[0]


# =========================================================================
# GET /api/requests/{slug} — public
# =========================================================================

class TestGetFileRequestPublic:

    @patch("app.public.file_requests.get_admin_client")
    def test_get_active_request(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row()]
        )

        resp = client.get("/api/requests/testslug")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Request"
        assert data["is_expired"] is False

    @patch("app.public.file_requests.get_admin_client")
    def test_get_nonexistent(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        resp = client.get("/api/requests/nonexistent")
        assert resp.status_code == 404

    @patch("app.public.file_requests.get_admin_client")
    def test_get_expired(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        now = datetime.now(timezone.utc)
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(expires_at=(now - timedelta(hours=1)).isoformat())]
        )

        resp = client.get("/api/requests/expired")
        assert resp.status_code == 200
        assert resp.json()["is_expired"] is True


# =========================================================================
# POST /api/requests/{slug}/upload — anonymous
# =========================================================================

class TestUploadToRequest:

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_success(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row()]
        )
        mock_client.storage.from_.return_value.upload.return_value = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "up-1", "filename": "test.pdf", "file_size": 100, "mime_type": "application/pdf", "created_at": datetime.now(timezone.utc).isoformat()}]
        )
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x" * 100), "application/pdf")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.pdf"
        assert data["file_size"] == 100

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_nonexistent_request(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        resp = client.post(
            "/api/requests/nope/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x"), "application/pdf")},
        )
        assert resp.status_code == 404

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_inactive_request(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(is_active=False)]
        )

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x"), "application/pdf")},
        )
        assert resp.status_code == 410

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_expired_request(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        now = datetime.now(timezone.utc)
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(expires_at=(now - timedelta(hours=1)).isoformat())]
        )

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x"), "application/pdf")},
        )
        assert resp.status_code == 410

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_max_files_reached(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(max_files=5, upload_count=5)]
        )

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x"), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "5 files" in resp.json()["detail"]

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_requires_name(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(require_name=True)]
        )

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x"), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "name" in resp.json()["detail"].lower()

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_requires_email(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(require_email=True)]
        )

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("test.pdf", io.BytesIO(b"x"), "application/pdf")},
            data={"uploader_name": "John"},
        )
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_with_uploader_info(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(require_name=True, require_email=True)]
        )
        mock_client.storage.from_.return_value.upload.return_value = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "up-info", "filename": "resume.pdf", "file_size": 200, "mime_type": "application/pdf", "created_at": datetime.now(timezone.utc).isoformat()}]
        )
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("resume.pdf", io.BytesIO(b"x" * 200), "application/pdf")},
            data={"uploader_name": "John Doe", "uploader_email": "john@example.com"},
        )
        assert resp.status_code == 200

    @patch("app.public.file_requests.get_admin_client")
    def test_upload_file_too_large(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row(max_file_size_mb=1)]
        )

        resp = client.post(
            "/api/requests/testslug/upload",
            files={"file": ("big.pdf", io.BytesIO(b"x" * (2 * 1024 * 1024)), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "too large" in resp.json()["detail"].lower()


# =========================================================================
# Dashboard: uploads list
# =========================================================================

class TestGetRequestUploads:

    def test_requires_auth(self, client):
        resp = client.get("/api/dashboard/requests/req-123/uploads")
        assert resp.status_code == 401

    @patch("app.internal.file_requests.get_admin_client")
    def test_not_found(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        resp = client.get("/api/dashboard/requests/nonexistent/uploads")
        assert resp.status_code == 404

    @patch("app.internal.file_requests.get_admin_client")
    def test_list_uploads(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Ownership check — needs slug, title, etc.
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_make_file_request_row()]
        )
        # Uploads query
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "up-1", "filename": "file1.pdf", "file_size": 1000, "mime_type": "application/pdf", "uploader_name": "Alice", "uploader_email": "alice@test.com", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": "up-2", "filename": "file2.docx", "file_size": 2000, "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "uploader_name": None, "uploader_email": None, "created_at": datetime.now(timezone.utc).isoformat()},
            ]
        )

        resp = client.get("/api/dashboard/requests/req-123/uploads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["uploads"]) == 2


# =========================================================================
# Dashboard: update request
# =========================================================================

class TestUpdateFileRequest:

    def test_requires_auth(self, client):
        resp = client.patch("/api/dashboard/requests/req-123", json={"title": "New"})
        assert resp.status_code == 401

    @patch("app.internal.file_requests.get_admin_client")
    def test_update_title(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-123"}]
        )
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-123", "slug": "abc", "title": "New title", "is_active": True}]
        )

        resp = client.patch("/api/dashboard/requests/req-123", json={"title": "New title"})
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

    @patch("app.internal.file_requests.get_admin_client")
    def test_update_no_valid_fields(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-123"}]
        )

        resp = client.patch("/api/dashboard/requests/req-123", json={"invalid_field": "value"})
        assert resp.status_code == 400

    @patch("app.internal.file_requests.get_admin_client")
    def test_update_not_found(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        resp = client.patch("/api/dashboard/requests/nonexistent", json={"title": "New"})
        assert resp.status_code == 404


# =========================================================================
# Dashboard: delete request
# =========================================================================

class TestDeleteFileRequest:

    def test_requires_auth(self, client):
        resp = client.delete("/api/dashboard/requests/req-123")
        assert resp.status_code == 401

    @patch("app.internal.file_requests.get_admin_client")
    def test_delete_success(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-del", "slug": "del-slug"}]
        )
        # Uploads query for storage cleanup
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_client.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_client.storage.from_.return_value.remove.return_value = MagicMock()

        resp = client.delete("/api/dashboard/requests/req-del")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @patch("app.internal.file_requests.get_admin_client")
    def test_delete_not_found(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        resp = client.delete("/api/dashboard/requests/nonexistent")
        assert resp.status_code == 404
