"""Tests for Custom Domains API endpoints."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from app.main import app


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_user():
    """A mock authenticated user."""
    user = MagicMock()
    user.id = "user-123"
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_team():
    """A mock team (pro plan)."""
    return {
        "id": "team-123",
        "name": "Test Team",
        "slug": "test-team",
        "plan": "pro",
        "owner_id": "user-123",
    }


@pytest.fixture
def mock_domain_record():
    """A mock domain record."""
    return {
        "id": "domain-123",
        "team_id": "team-123",
        "domain": "files.company.com",
        "status": "pending",
        "verification_token": "abc123token",
        "verified_at": None,
        "ssl_status": "pending",
        "ssl_issued_at": None,
        "brand_logo_url": None,
        "brand_color": None,
        "brand_favicon_url": None,
        "created_at": "2026-05-31T12:00:00Z",
        "updated_at": "2026-05-31T12:00:00Z",
    }


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestDomainModels:
    """Test Pydantic model validation."""

    def test_add_domain_valid(self):
        from models.domain import AddDomainInput
        d = AddDomainInput(domain="files.company.com")
        assert d.domain == "files.company.com"

    def test_add_domain_with_subdomain(self):
        from models.domain import AddDomainInput
        d = AddDomainInput(domain="share.my-company.co.uk")
        assert d.domain == "share.my-company.co.uk"

    def test_add_domain_invalid_pattern(self):
        from models.domain import AddDomainInput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AddDomainInput(domain="INVALID DOMAIN!")

    def test_add_domain_too_short(self):
        from models.domain import AddDomainInput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AddDomainInput(domain="ab")

    def test_brand_color_valid(self):
        from models.domain import UpdateDomainBrandInput
        b = UpdateDomainBrandInput(brand_color="#FF5701")
        assert b.brand_color == "#FF5701"

    def test_brand_color_invalid(self):
        from models.domain import UpdateDomainBrandInput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateDomainBrandInput(brand_color="not-a-color")

    def test_brand_color_invalid_no_hash(self):
        from models.domain import UpdateDomainBrandInput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateDomainBrandInput(brand_color="FF5701")

    def test_brand_defaults_none(self):
        from models.domain import UpdateDomainBrandInput
        b = UpdateDomainBrandInput()
        assert b.brand_logo_url is None
        assert b.brand_color is None
        assert b.brand_favicon_url is None

    def test_domain_verification_status(self):
        from models.domain import DomainVerificationStatus
        from datetime import datetime, timezone
        s = DomainVerificationStatus(
            domain="files.company.com",
            status="active",
            txt_record="abc123",
            verified_at=datetime.now(timezone.utc),
            ssl_status="pending",
            ssl_issued_at=None,
            message="Verified!",
        )
        assert s.status == "active"
        assert s.message == "Verified!"


# ---------------------------------------------------------------------------
# Route existence tests
# ---------------------------------------------------------------------------

class TestDomainRoutesExist:
    """Verify all expected domain routes are registered in the app."""

    def test_all_domain_routes_registered(self):
        from app.main import app
        domain_routes = [
            r for r in app.routes
            if hasattr(r, "path") and "domain" in r.path.lower()
        ]
        paths = {r.path for r in domain_routes}
        expected = {
            "/api/dashboard/teams/{slug}/domains",
            "/api/dashboard/teams/{slug}/domains/{domain_id}",
            "/api/dashboard/teams/{slug}/domains/{domain_id}/verify",
            "/api/dashboard/teams/{slug}/domains/{domain_id}/brand",
            "/api/dashboard/domains/resolve/{domain}",
        }
        assert expected.issubset(paths), f"Missing routes: {expected - paths}"

    def test_post_add_domain(self):
        from app.main import app
        routes = [r for r in app.routes if hasattr(r, "path")]
        post_domains = [
            r for r in routes
            if r.path == "/api/dashboard/teams/{slug}/domains"
            and hasattr(r, "methods") and "POST" in r.methods
        ]
        assert len(post_domains) == 1

    def test_verify_endpoint_exists(self):
        from app.main import app
        routes = [r for r in app.routes if hasattr(r, "path")]
        verify_routes = [
            r for r in routes
            if r.path == "/api/dashboard/teams/{slug}/domains/{domain_id}/verify"
            and hasattr(r, "methods") and "POST" in r.methods
        ]
        assert len(verify_routes) == 1

    def test_brand_patch_endpoint_exists(self):
        from app.main import app
        routes = [r for r in app.routes if hasattr(r, "path")]
        brand_routes = [
            r for r in routes
            if r.path == "/api/dashboard/teams/{slug}/domains/{domain_id}/brand"
            and hasattr(r, "methods") and "PATCH" in r.methods
        ]
        assert len(brand_routes) == 1


# ---------------------------------------------------------------------------
# Domain helper tests
# ---------------------------------------------------------------------------

class TestDomainHelpers:
    """Test utility functions in domains module."""

    def test_generate_verification_token(self):
        from app.dashboard.domains import _generate_verification_token
        token1 = _generate_verification_token()
        token2 = _generate_verification_token()
        assert len(token1) == 64  # 32 bytes as hex
        assert token1 != token2  # should be unique
        assert all(c in "0123456789abcdef" for c in token1)

    def test_verification_prefix(self):
        from app.dashboard.domains import VERIFICATION_PREFIX
        assert VERIFICATION_PREFIX == "_dropitx-verify"

    def test_expected_cname_target(self):
        from app.dashboard.domains import EXPECTED_CNAME_TARGET
        assert EXPECTED_CNAME_TARGET == "dropitx.com"


# ---------------------------------------------------------------------------
# Public resolution endpoint
# ---------------------------------------------------------------------------

class TestResolveCustomDomain:
    @patch("app.dashboard.domains.get_admin_client")
    def test_resolve_custom_domain_not_configured(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        client = TestClient(app)
        resp = client.get("/api/dashboard/domains/resolve/some-domain.com")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Domain not configured"
