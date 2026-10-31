"""Live-DB tests: public share metadata, invite lookup, and public profile share lists.

Runs against the real Postgres + MinIO from CI. Only authentication is overridden.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import User
from app.main import app
from core.security import hash_password
from core.supabase import get_admin_client
from tests.test_share_access_control import PRIVATE_BODY, _act_as, _Seed, _walk_keys

SECRET_KEYS = {"password_hash", "delete_token", "content", "content_text", "storage_path"}
BODY = "<h1>meta body</h1>"


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seed():
    s = _Seed()
    yield s
    s.cleanup()


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _view_count(db, share_id: str) -> int:
    return db.table("shares").select("view_count").eq("id", share_id).execute().data[0]["view_count"]


def _view_rows(db, share_id: str) -> int:
    return len(db.table("share_views").select("id").eq("share_id", share_id).execute().data)


# ---------------------------------------------------------------------------
# GET /api/shares/{slug}
# ---------------------------------------------------------------------------

class TestShareMeta:
    def test_public_share_returns_metadata_without_secrets(self, client, seed):
        owner = seed.user()
        share = seed.share(
            owner, body=BODY, is_private=False, language="html", file_size=len(BODY),
        )
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == share["id"]
        assert body["slug"] == share["slug"]
        assert body["filename"] == share["filename"]
        assert body["title"] == "ACL fixture"
        assert body["mime_type"] == "text/html"
        assert body["language"] == "html"
        assert body["file_size"] == len(BODY)
        assert body["view_count"] == 0
        assert body["is_private"] is False
        assert body["has_password"] is False
        assert body["burn_after_reading"] is False
        assert body["burned"] is False
        assert body["encrypted"] is False
        assert body["is_owner"] is False
        assert body["group_id"] is None
        assert body["group_files"] == []
        assert body["created_at"] and body["expires_at"] is None
        assert not SECRET_KEYS & set(_walk_keys(body))
        assert BODY not in resp.text
        assert "user_id" not in body

    def test_owner_is_flagged_and_other_signed_in_user_is_not(self, client, seed):
        owner, other = seed.user(), seed.user()
        share = seed.share(owner, body=BODY, is_private=False)

        _act_as(owner)
        assert client.get(f"/api/shares/{share['slug']}").json()["is_owner"] is True

        _act_as(other)
        assert client.get(f"/api/shares/{share['slug']}").json()["is_owner"] is False

    def test_private_share_is_hidden_from_everyone_but_the_owner(self, client, seed):
        owner, other, teammate = seed.user(), seed.user(), seed.user()
        share = seed.share(owner)
        seed.team_with_share(teammate, share)

        _act_as(None)
        missing = client.get(f"/api/shares/does-not-exist-{uuid.uuid4().hex}")
        assert missing.status_code == 404
        anon = client.get(f"/api/shares/{share['slug']}")
        assert anon.status_code == 404
        assert anon.json() == missing.json()

        for viewer in (other, teammate):
            _act_as(viewer)
            resp = client.get(f"/api/shares/{share['slug']}")
            assert resp.status_code == 404
            assert resp.json() == missing.json()

        _act_as(owner)
        resp = client.get(f"/api/shares/{share['slug']}")
        assert resp.status_code == 200
        assert resp.json()["is_private"] is True
        assert resp.json()["is_owner"] is True
        assert PRIVATE_BODY not in resp.text

    def test_password_share_reports_has_password_and_leaks_no_hash(self, client, seed):
        owner = seed.user()
        pw_hash = hash_password("hunter2")
        share = seed.share(owner, is_private=False, password_hash=pw_hash)
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_password"] is True
        assert body["is_private"] is False
        keys = set(_walk_keys(body))
        assert "password_hash" not in keys and "delete_token" not in keys
        assert pw_hash not in resp.text
        assert share["delete_token"] not in resp.text

    def test_group_share_lists_only_siblings_the_caller_may_see(self, client, seed):
        owner, other = seed.user(), seed.user()
        group = seed.group(owner)
        first = seed.share(owner, is_private=False, group_id=group, file_size=10)
        second = seed.share(owner, is_private=False, group_id=group, file_size=20, max_downloads=3)
        seed.share(owner, is_private=True, group_id=group)
        seed.share(owner, is_private=False, group_id=group, password_hash=hash_password("pw"))
        seed.share(owner, is_private=False, group_id=group, expires_at=_past())

        _act_as(other)
        resp = client.get(f"/api/shares/{first['slug']}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["group_id"] == group
        assert [f["slug"] for f in body["group_files"]] == [first["slug"], second["slug"]]
        listed = body["group_files"][1]
        assert set(listed) == {
            "slug", "filename", "mime_type", "file_size", "download_count", "max_downloads",
        }
        assert listed["file_size"] == 20 and listed["max_downloads"] == 3
        assert not SECRET_KEYS & set(_walk_keys(body))

    def test_group_owner_sees_private_and_password_siblings(self, client, seed):
        owner = seed.user()
        group = seed.group(owner)
        public = seed.share(owner, is_private=False, group_id=group)
        private = seed.share(owner, is_private=True, group_id=group)
        locked = seed.share(owner, is_private=False, group_id=group, password_hash=hash_password("pw"))

        _act_as(owner)
        body = client.get(f"/api/shares/{public['slug']}").json()

        assert {f["slug"] for f in body["group_files"]} == {
            public["slug"], private["slug"], locked["slug"],
        }

    def test_expired_share_is_410_and_is_not_deleted(self, client, seed):
        share = seed.share(seed.user(), is_private=False, expires_at=_past())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}")

        assert resp.status_code == 410
        assert seed.db.table("shares").select("id").eq("id", share["id"]).execute().data

    def test_expired_private_share_is_404_for_a_stranger(self, client, seed):
        share = seed.share(seed.user(), is_private=True, expires_at=_past())
        _act_as(None)

        assert client.get(f"/api/shares/{share['slug']}").status_code == 404

    def test_burned_share_reports_burned(self, client, seed):
        share = seed.share(seed.user(), is_private=False, burn_after_reading=True, burned=True)
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}")

        assert resp.status_code == 200
        assert resp.json()["burned"] is True
        assert resp.json()["burn_after_reading"] is True

    def test_repeated_metadata_calls_do_not_count_as_views(self, client, seed):
        share = seed.share(seed.user(), body=BODY, is_private=False)
        _act_as(None)

        for _ in range(2):
            assert client.get(f"/api/shares/{share['slug']}").status_code == 200
        time.sleep(0.5)

        assert _view_count(seed.db, share["id"]) == 0
        assert _view_rows(seed.db, share["id"]) == 0
        assert client.get(f"/api/shares/{share['slug']}").json()["view_count"] == 0

    def test_burn_after_reading_share_survives_metadata_calls(self, client, seed):
        share = seed.share(seed.user(), body=BODY, is_private=False, burn_after_reading=True)
        _act_as(None)

        for _ in range(2):
            meta = client.get(f"/api/shares/{share['slug']}")
            assert meta.status_code == 200
            assert meta.json()["burn_after_reading"] is True

        content = client.get(f"/api/shares/{share['slug']}/content")
        assert content.status_code == 200
        assert content.json()["content"] == BODY

    def test_neighbouring_share_routes_are_not_shadowed(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, body=BODY, is_private=False)
        _act_as(owner)

        content = client.get(f"/api/shares/{share['slug']}/content")
        status = client.get(f"/api/shares/{share['slug']}/download-status")
        versions = client.get(f"/api/shares/{share['slug']}/versions")
        meta = client.get(f"/api/shares/{share['slug']}")

        assert content.status_code == 200 and content.json()["content"] == BODY
        assert status.status_code == 200 and "download_count" in status.json()
        assert versions.status_code == 200
        assert meta.status_code == 200 and "slug" in meta.json()
        assert "content" not in set(_walk_keys(meta.json()))

        assert client.delete(f"/api/shares/{share['slug']}").status_code == 200
        assert client.get(f"/api/shares/{share['slug']}").status_code == 404


# ---------------------------------------------------------------------------
# GET /api/invites/{token}
# ---------------------------------------------------------------------------

class _InviteSeed:
    def __init__(self, seed: _Seed):
        self.seed = seed
        self.db = seed.db

    def invite(self, *, status: str = "pending", expires_at: str | None = None, role: str = "editor") -> dict:
        inviter = self.seed.user()
        self.db.table("user_profiles").insert(
            {"user_id": inviter.id, "display_name": "Ida Inviter"}
        ).execute()
        team = self.db.table("teams").insert(
            {"name": "Lookup Team", "slug": f"lt-{uuid.uuid4().hex[:10]}", "owner_id": inviter.id}
        ).execute().data[0]
        self.seed.teams.append(team["id"])
        email = f"invitee-{uuid.uuid4().hex[:8]}@example.com"
        row = {
            "team_id": team["id"], "email": email, "role": role, "status": status,
            "invited_by": inviter.id, "token": f"tok-{uuid.uuid4().hex}",
        }
        if expires_at:
            row["expires_at"] = expires_at
        created = self.db.table("team_invitations").insert(row).execute().data[0]
        return {**created, "team": team, "inviter": inviter}


@pytest.fixture
def invites(seed):
    yield _InviteSeed(seed)


class TestInviteLookup:
    def test_valid_invite_returns_accept_page_data_for_an_anonymous_caller(self, client, invites):
        invite = invites.invite(role="viewer")
        _act_as(None)

        resp = client.get(f"/api/invites/{invite['token']}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["team_name"] == "Lookup Team"
        assert body["team_slug"] == invite["team"]["slug"]
        assert body["inviter_display_name"] == "Ida Inviter"
        assert body["role"] == "viewer"
        assert body["status"] == "pending"
        assert body["expires_at"]
        assert body["email_matches"] is None
        assert "invitee_email" not in body or body["invitee_email"] is None
        assert invite["email"] not in resp.text
        assert invite["token"] not in resp.text
        assert not {"token", "email", "invited_by", "team_id", "id"} & set(body)

    def test_invitee_email_is_returned_only_when_the_caller_email_matches(self, client, invites, seed):
        invite = invites.invite()

        matching = seed.user()
        seed.db.table("auth.users").update({"email": invite["email"]}).eq("id", matching.id).execute()
        _act_as(User(id=matching.id, email=invite["email"].upper()))
        body = client.get(f"/api/invites/{invite['token']}").json()
        assert body["invitee_email"] == invite["email"]
        assert body["email_matches"] is True

        _act_as(seed.user())
        resp = client.get(f"/api/invites/{invite['token']}")
        assert resp.json()["email_matches"] is False
        assert resp.json().get("invitee_email") is None
        assert invite["email"] not in resp.text

    def test_unknown_token_is_404(self, client):
        _act_as(None)

        resp = client.get(f"/api/invites/nope-{uuid.uuid4().hex}")

        assert resp.status_code == 404

    def test_expired_invite_is_410(self, client, invites):
        invite = invites.invite(expires_at=_past())
        _act_as(None)

        resp = client.get(f"/api/invites/{invite['token']}")

        assert resp.status_code == 410

    @pytest.mark.parametrize("status", ["accepted", "declined", "revoked"])
    def test_settled_invite_reports_its_status(self, client, invites, status):
        invite = invites.invite(status=status)
        _act_as(None)

        resp = client.get(f"/api/invites/{invite['token']}")

        assert resp.status_code == 200
        assert resp.json()["status"] == status

    def test_lookup_does_not_change_the_invite(self, client, invites):
        invite = invites.invite()
        _act_as(None)

        client.get(f"/api/invites/{invite['token']}")
        client.get(f"/api/invites/{invite['token']}")

        row = get_admin_client().table("team_invitations").select("status").eq("id", invite["id"]).execute().data[0]
        assert row["status"] == "pending"


# ---------------------------------------------------------------------------
# Public profile: shares are found by the owner's Firebase uid
# ---------------------------------------------------------------------------

class TestPublicProfileShares:
    def test_public_share_is_listed_and_counted(self, client, seed):
        owner = seed.user()
        username = f"prof-{uuid.uuid4().hex[:10]}"
        seed.db.table("user_profiles").insert(
            {"user_id": owner.id, "username": username, "display_name": "Pat", "is_public": True}
        ).execute()
        public = seed.share(owner, is_private=False, view_count=7)
        seed.share(owner, is_private=True)
        _act_as(None)

        profile = client.get(f"/api/u/{username}")
        listing = client.get(f"/api/u/{username}/shares")

        assert profile.status_code == 200
        assert profile.json()["share_count"] == 1
        assert profile.json()["total_views"] == 7
        assert listing.status_code == 200
        assert [s["slug"] for s in listing.json()["shares"]] == [public["slug"]]
