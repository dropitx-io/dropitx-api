"""Live-DB tests: who may read a share, and what the team listing exposes.

Runs against the real Postgres + MinIO from CI. Only authentication is
overridden (dependency_overrides for get_current_user / get_optional_user);
the share rows, storage objects, team membership and queries are real.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.dependencies import User, get_current_user, get_optional_user
from app.main import app
from core.supabase import get_admin_client

SECRET_KEYS = {"password_hash", "delete_token"}
PRIVATE_BODY = "<h1>private body</h1>"
PUBLIC_BODY = "<h1>public body</h1>"


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _act_as(user: User | None) -> None:
    """Authenticate every request as `user` (None = anonymous)."""
    app.dependency_overrides.clear()
    if user is None:
        app.dependency_overrides[get_optional_user] = lambda: None
        return
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def _walk_keys(node):
    """Yield every dict key found anywhere in a JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


class _Seed:
    """Rows created by one test, removed on teardown."""

    def __init__(self):
        self.db = get_admin_client()
        self.users: list[str] = []
        self.shares: list[str] = []
        self.teams: list[str] = []
        self.objects: list[str] = []

    def user(self) -> User:
        uid = f"acl-{uuid.uuid4().hex}"
        self.db.table("auth.users").insert({"id": uid, "email": f"{uid}@example.com"}).execute()
        self.users.append(uid)
        return User(id=uid, email=f"{uid}@example.com")

    def share(self, owner: User, *, body: str = PRIVATE_BODY, **overrides) -> dict:
        slug = f"acl-{uuid.uuid4().hex[:12]}"
        path = f"shares/{slug}.html"
        self.db.storage.from_("html-files").upload(
            path, body.encode(), file_options={"content-type": "text/html"}
        )
        self.objects.append(path)
        row = {
            "slug": slug,
            "title": "ACL fixture",
            "filename": f"{slug}.html",
            "storage_path": path,
            "mime_type": "text/html",
            "source": "upload",
            "user_id": owner.id,
            "is_private": True,
            "delete_token": f"tok-{uuid.uuid4().hex}",
        }
        row.update(overrides)
        created = self.db.table("shares").insert(row).execute().data[0]
        self.shares.append(created["id"])
        return created

    def team_with_share(self, member: User, share: dict) -> str:
        slug = f"acl-team-{uuid.uuid4().hex[:10]}"
        team = self.db.table("teams").insert(
            {"name": "ACL team", "slug": slug, "owner_id": share["user_id"]}
        ).execute().data[0]
        self.teams.append(team["id"])
        self.db.table("team_members").insert(
            {"team_id": team["id"], "user_id": member.id, "role": "viewer"}
        ).execute()
        self.db.table("team_shares").insert(
            {"team_id": team["id"], "share_id": share["id"], "shared_by": share["user_id"]}
        ).execute()
        return slug

    def cleanup(self):
        for team_id in self.teams:
            self.db.table("teams").delete().eq("id", team_id).execute()
        for share_id in self.shares:
            self.db.table("shares").delete().eq("id", share_id).execute()
        if self.objects:
            self.db.storage.from_("html-files").remove(self.objects)
        for uid in self.users:
            self.db.table("auth.users").delete().eq("id", uid).execute()


@pytest.fixture
def seed():
    s = _Seed()
    yield s
    s.cleanup()


@pytest.fixture
def missing_share_body(client):
    _act_as(None)
    resp = client.get(f"/api/shares/does-not-exist-{uuid.uuid4().hex}/content")
    assert resp.status_code == 404
    return resp.json()


# ---------------------------------------------------------------------------
# Private shares: content and preview
# ---------------------------------------------------------------------------

class TestPrivateShareContent:
    def test_anonymous_gets_404_for_private_content(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body
        assert PRIVATE_BODY not in resp.text

    def test_owner_reads_private_content(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 200
        assert resp.json()["content"] == PRIVATE_BODY
        assert resp.json()["is_private"] is True

    def test_non_owner_user_gets_404_for_private_content(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_team_member_gets_404_for_private_content(self, client, seed, missing_share_body):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(owner)
        seed.team_with_share(teammate, share)
        _act_as(teammate)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_burned_private_share_is_404_not_410_for_anonymous(self, client, seed, missing_share_body):
        share = seed.share(seed.user(), burned=True)
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_public_share_content_stays_anonymous(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 200
        assert resp.json()["content"] == PUBLIC_BODY


class TestPrivateSharePreview:
    def test_anonymous_gets_404_for_private_preview(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_non_owner_user_gets_404_for_private_preview(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_previews_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 200
        assert resp.json()["slug"] == share["slug"]

    def test_public_share_preview_stays_anonymous(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
        _act_as(None)

        assert client.get(f"/api/shares/{share['slug']}/preview").status_code == 200


# ---------------------------------------------------------------------------
# Private shares: the other two routes that hand out the content
# ---------------------------------------------------------------------------

class TestPrivateShareDownloadAndUnlock:
    def test_anonymous_gets_404_for_private_download(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/download")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_downloads_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/download")

        assert resp.status_code == 200
        assert resp.text == PRIVATE_BODY

    def test_non_owner_gets_404_for_private_unlock(self, client, seed, missing_share_body):
        from core.security import hash_password

        share = seed.share(seed.user(), password_hash=hash_password("hunter2"))
        _act_as(seed.user())

        resp = client.post(f"/api/shares/{share['slug']}/unlock", json={"password": "hunter2"})

        assert resp.status_code == 404
        assert resp.json() == missing_share_body
        assert PRIVATE_BODY not in resp.text


# ---------------------------------------------------------------------------
# Team shares listing never exposes secrets
# ---------------------------------------------------------------------------

class TestTeamSharesListing:
    def test_member_listing_has_no_secrets_and_reports_has_password(self, client, seed):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(
            owner, password_hash="$2b$12$fixturehashfixturehashfixtur", is_private=False
        )
        team_slug = seed.team_with_share(teammate, share)
        _act_as(teammate)

        resp = client.get(f"/api/dashboard/teams/{team_slug}/shares")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert not SECRET_KEYS & set(_walk_keys(items))
        assert share["delete_token"] not in resp.text
        assert "fixturehash" not in resp.text

        nested = items[0]["shares"]
        assert nested["has_password"] is True
        assert nested["id"] == share["id"]
        assert nested["slug"] == share["slug"]
        assert nested["filename"] == share["filename"]
        assert nested["user_id"] == owner.id
        assert nested["is_private"] is False
        for field in ("title", "mime_type", "view_count", "created_at", "expires_at",
                      "burn_after_reading", "encrypted"):
            assert field in nested

    def test_listing_reports_has_password_false_when_unprotected(self, client, seed):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(owner, is_private=False)
        team_slug = seed.team_with_share(teammate, share)
        _act_as(teammate)

        resp = client.get(f"/api/dashboard/teams/{team_slug}/shares")

        assert resp.status_code == 200
        assert resp.json()[0]["shares"]["has_password"] is False
