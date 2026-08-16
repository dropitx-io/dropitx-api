"""Live-DB tests for GET /api/auth/session provisioning.

Requires `docker compose up -d`. These tests exercise the real
`provision_firebase_user` RPC through the full HTTP flow (including the
401 -> session -> 200 provisioning contract), not a mocked one — the mocked
tests in tests/test_auth_session.py cannot catch RPC-level PL/pgSQL errors.

Only the Firebase JWT cryptographic verification is faked: /api/auth/session
honors the dependency_overrides[get_firebase_claims] override, while
get_current_user (guarding /api/v1/keys) calls get_firebase_claims directly,
so the verifier is patched per the tests/test_dependencies.py convention.
Everything downstream — the RPC, the DB lookups — runs against real Postgres.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_firebase_claims
from app.main import app
from core.supabase import get_admin_client

AUTH = {"Authorization": "Bearer test-token"}

_claims: dict = {}


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_firebase_jwt():
    with patch(
        "app.dependencies.verify_firebase_jwt",
        side_effect=lambda _token: dict(_claims),
    ):
        yield


@pytest.fixture
def client():
    return TestClient(app)


def _override_claims(uid: str, email: str):
    _claims.clear()
    _claims.update({"sub": uid, "email": email, "email_verified": True})
    app.dependency_overrides[get_firebase_claims] = lambda: dict(_claims)


def _delete_user(uid: str):
    get_admin_client().table("auth.users").delete().eq("id", uid).execute()


def test_full_provision_and_401_then_success_flow(client):
    uid = f"test-uid-{uuid.uuid4().hex}"
    email = f"{uid}@example.com"
    _override_claims(uid, email)

    try:
        # Fresh uid was never provisioned -> protected route must 401.
        protected = client.get("/api/v1/keys", headers=AUTH)
        assert protected.status_code == 401
        assert protected.json()["detail"]["code"] == "user_not_provisioned"

        # GREEN: the fixed RPC provisions and returns the profile.
        first = client.get("/api/auth/session", headers=AUTH)
        assert first.status_code == 200
        assert first.json()["profile"]["user_id"] == uid

        # Second call with a different email: still 200, still exactly one
        # user_profiles row, and the email update is reflected.
        updated_email = f"updated-{uid}@example.com"
        _override_claims(uid, updated_email)
        second = client.get("/api/auth/session", headers=AUTH)
        assert second.status_code == 200
        assert second.json()["email"] == updated_email
        assert second.json()["profile"]["user_id"] == uid

        profiles = (
            get_admin_client()
            .table("user_profiles")
            .select("id")
            .eq("user_id", uid)
            .execute()
        )
        assert len(profiles.data) == 1

        # Provisioned now -> the same protected route returns 200.
        after_provisioning = client.get("/api/v1/keys", headers=AUTH)
        assert after_provisioning.status_code == 200
    finally:
        _delete_user(uid)
